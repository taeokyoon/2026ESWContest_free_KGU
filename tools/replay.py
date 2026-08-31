"""Car Hacking Challenge 데이터셋을 CAN 버스에 재생한다.

인자 없이 실행하면 보드 실측 테스트를 처음부터 끝까지 안내한다.
데이터셋 파일과 포트를 찾고, 재생 속도를 원본에서 계산하고,
정상 재생과 공격 재생을 순서대로 진행한다.

    python replay.py

파일을 지정하면 그 파일만 재생한다.

    python replay.py Pre_train_D_0.csv --port COM7
    python replay.py Pre_train_D_1.csv --port COM7 --skip 100000 --limit 50000
"""

import argparse
import csv
import sys
import time
from array import array
from pathlib import Path

import can

WINDOW_SIZE = 32
NORMAL_FRAMES = 20000
ATTACK_FRAMES = 26000
SEGMENT = 50000
LEAD_FRAMES = 3200
FALLBACK_RATE = 2400.0

TRAIN_FILES = (
    "pre_train_d_0.csv", "pre_train_d_1.csv", "pre_train_d_2.csv",
    "pre_train_s_0.csv", "pre_train_s_1.csv", "pre_train_s_2.csv",
)


def parse_args():
    p = argparse.ArgumentParser(description="CAN 데이터셋 재생기")
    p.add_argument("csv_path", nargs="?", help="데이터셋 CSV 경로 (생략하면 안내 모드)")
    p.add_argument("--port", help="USB-CAN 어댑터 포트 (생략하면 자동 탐색)")
    p.add_argument("--bitrate", type=int, default=500000, help="CAN 비트레이트 (기본 500000)")
    p.add_argument("--baudrate", type=int, default=2000000, help="어댑터 시리얼 속도 (기본 2000000)")
    p.add_argument("--limit", type=int, default=NORMAL_FRAMES, help="보낼 프레임 수 (0=전부)")
    p.add_argument("--rate", type=float, help="초당 프레임 수 (생략하면 원본에서 계산, 0=제한 없음)")
    p.add_argument("--skip", type=int, default=0, help="앞에서 건너뛸 프레임 수")
    return p.parse_args()


IGNORED_PORTS = ("bluetooth", "debug-console", "wlan-debug")


def serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    ports = list(list_ports.comports())
    usable = [p for p in ports if not is_ignored(p)]
    return usable or ports


def is_ignored(port):
    text = f"{port.device} {port.description or ''}".lower()
    return any(word in text for word in IGNORED_PORTS)


def pick_port(explicit):
    if explicit:
        return explicit

    ports = serial_ports()
    if ports is None:
        print("pyserial이 없습니다.  pip install pyserial", file=sys.stderr)
        return None
    if not ports:
        print("연결된 시리얼 포트가 없습니다. 어댑터가 꽂혀 있는지 확인하세요.", file=sys.stderr)
        return None
    if len(ports) == 1:
        print(f"포트 자동 선택: {ports[0].device}  ({ports[0].description})")
        return ports[0].device

    print("\n포트가 여러 개입니다. 어댑터가 꽂힌 포트를 고르세요.")
    for i, p in enumerate(ports, 1):
        print(f"  {i}) {p.device}  {p.description}")
    while True:
        try:
            answer = input("번호 입력: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(ports):
            return ports[int(answer) - 1].device
        print("목록에 있는 번호를 입력하세요.")


def find_csv_files():
    roots = [Path(__file__).resolve().parent, Path.cwd()]
    found = {}
    for root in roots:
        try:
            for path in root.rglob("*.csv"):
                resolved = path.resolve()
                if resolved not in found and resolved.is_file():
                    found[resolved] = resolved.stat().st_size
        except OSError:
            continue
    return sorted(found, key=lambda p: found[p])


def robust_fps(gaps):
    """이어붙인 파일의 시간 공백·역행에 흔들리지 않는 재생 속도.

    전체 구간을 프레임 수로 나누면 공백 하나에 결과가 무너지므로,
    양수 간격만 모아 상위 1%를 잘라낸 평균을 쓴다.
    """
    positive = sorted(g for g in gaps if g > 0)
    if not positive:
        return None
    cut = positive[: max(1, int(len(positive) * 0.99))]
    mean = sum(cut) / len(cut)
    return 1.0 / mean if mean > 0 else None


def scan_csv(path):
    total = 0
    attacks = 0
    gaps = array("d")
    prev_ts = None
    segments = {}
    transitions = []
    normal_run = 0
    was_attack = False

    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return None
        index = {name: i for i, name in enumerate(header)}
        ts_i = index.get("Timestamp")
        class_i = index.get("Class")
        if ts_i is None or "Arbitration_ID" not in index:
            return None

        for row in reader:
            if not row:
                continue
            total += 1
            try:
                stamp = float(row[ts_i])
            except (ValueError, IndexError):
                stamp = None
            if stamp is not None:
                if prev_ts is not None:
                    gaps.append(stamp - prev_ts)
                prev_ts = stamp

            is_attack = class_i is not None and row[class_i] != "Normal"
            if is_attack:
                attacks += 1
                start = ((total - 1) // SEGMENT) * SEGMENT
                segments[start] = segments.get(start, 0) + 1
                if not was_attack and normal_run >= LEAD_FRAMES:
                    transitions.append(total - 1)
                normal_run = 0
            else:
                normal_run += 1
            was_attack = is_attack

    if total == 0:
        return None

    densest = max(segments, key=segments.get) if segments else 0
    skip = 0
    if segments:
        limit = densest + SEGMENT
        usable = [t for t in transitions if t <= limit]
        anchor = usable[-1] if usable else (transitions[0] if transitions else densest)
        skip = max(0, anchor - LEAD_FRAMES)

    return {
        "path": path,
        "total": total,
        "attacks": attacks,
        "fps": robust_fps(gaps),
        "skip": skip,
        "dense": segments.get(densest, 0),
        "training": path.name.lower() in TRAIN_FILES,
    }


def choose_files():
    paths = find_csv_files()
    if not paths:
        return None, None

    print("데이터셋을 찾는 중입니다. 파일이 크면 잠시 걸립니다.")
    normal = None
    attack = None
    for path in paths:
        info = scan_csv(path)
        if info is None:
            continue
        label = "정상만" if info["attacks"] == 0 else f"공격 {info['attacks']:,}행"
        mark = " (학습에 쓴 파일)" if info["training"] else ""
        print(f"  {path.name:<34} {info['total']:>9,}행  {label}{mark}")
        if info["attacks"] == 0:
            if normal is None:
                normal = info
        elif attack is None or (attack["training"] and not info["training"]):
            attack = info
        if normal is not None and attack is not None and not attack["training"]:
            break
    return normal, attack


def load_frames(path, skip, limit):
    frames = []
    with open(path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i < skip:
                continue
            if limit and len(frames) >= limit:
                break

            data = bytes.fromhex(row["Data"].replace(" ", ""))
            dlc = int(row["DLC"])
            frames.append(
                can.Message(
                    arbitration_id=int(row["Arbitration_ID"], 16),
                    data=data[:dlc],
                    is_extended_id=False,
                )
            )
    return frames


def open_bus(port, baudrate, bitrate):
    try:
        return can.interface.Bus(
            interface="seeedstudio",
            channel=port,
            baudrate=baudrate,
            bitrate=bitrate,
        )
    except Exception as e:
        print(f"\n{port} 를 열지 못했습니다: {e}", file=sys.stderr)
        ports = serial_ports()
        if ports:
            print("사용 가능한 포트:", file=sys.stderr)
            for p in ports:
                print(f"  {p.device}  {p.description}", file=sys.stderr)
        elif ports is None:
            print("pyserial이 없습니다.  pip install pyserial", file=sys.stderr)
        else:
            print("연결된 시리얼 포트가 없습니다.", file=sys.stderr)
        return None


def send_frames(bus, frames, rate):
    interval = 1.0 / rate if rate and rate > 0 else 0.0
    sent = 0
    started = time.perf_counter()
    next_due = started

    try:
        for msg in frames:
            if interval:
                now = time.perf_counter()
                if next_due > now:
                    time.sleep(next_due - now)
                next_due += interval

            bus.send(msg)
            sent += 1

            if sent % 2000 == 0:
                elapsed = time.perf_counter() - started
                print(f"  {sent:,} / {len(frames):,}  ({sent / elapsed:,.0f} fps)")
    except KeyboardInterrupt:
        print("\n중단됨")

    elapsed = time.perf_counter() - started
    if sent == 0 or elapsed <= 0:
        print("\n전송된 프레임이 없습니다.")
        return sent

    achieved = sent / elapsed
    print(f"\n완료: {sent:,}개 전송, {elapsed:.1f}초, 평균 {achieved:,.0f} fps")
    if rate and rate > 0 and achieved < rate * 0.9:
        print("[주의] 목표 속도에 못 미쳤습니다. PC나 어댑터가 병목입니다.")
    return sent


def describe(info, skip, limit):
    count = info["total"] - skip
    if limit:
        count = min(count, limit)
    seconds = count / info["fps"] if info["fps"] else 0
    print(f"  파일     {info['path'].name}")
    print(f"  구간     {skip:,}행부터 {count:,}프레임 (윈도우 약 {count // WINDOW_SIZE:,}개)")
    if seconds:
        print(f"  예상시간 약 {seconds:.0f}초")
    return count


def run_phase(bus, info, skip, limit, rate):
    frames = load_frames(info["path"], skip, limit)
    if not frames:
        print("보낼 프레임이 없습니다.", file=sys.stderr)
        return 0
    ids = {m.arbitration_id for m in frames}
    print(f"  고유 ID {len(ids)}종류 / 재생 속도 {rate:,.0f} fps")
    print("  2초 후 시작합니다...")
    time.sleep(2)
    return send_frames(bus, frames, rate)


def wait_for_user(message):
    print(f"\n{message}")
    try:
        input("준비되면 Enter를 누르세요... ")
    except (EOFError, KeyboardInterrupt):
        return False
    return True


def run_single(args):
    path = Path(args.csv_path)
    if not path.exists():
        print(f"{path} 를 찾을 수 없습니다.", file=sys.stderr)
        return 1

    port = pick_port(args.port)
    if port is None:
        return 1
    bus = open_bus(port, args.baudrate, args.bitrate)
    if bus is None:
        return 1

    print(f"CSV 읽는 중: {path}")
    rate = args.rate
    if rate is None:
        info = scan_csv(path)
        rate = info["fps"] if info and info["fps"] else FALLBACK_RATE
        print(f"재생 속도를 원본에서 계산했습니다: {rate:,.0f} fps")

    frames = load_frames(path, args.skip, args.limit)
    if not frames:
        print("보낼 프레임이 없습니다.", file=sys.stderr)
        bus.shutdown()
        return 1

    ids = {m.arbitration_id for m in frames}
    print(f"프레임 {len(frames):,}개 / 고유 ID {len(ids)}종류 / 윈도우 약 {len(frames) // WINDOW_SIZE:,}개")
    print(f"{port} 열림. 2초 후 시작합니다...")
    time.sleep(2)
    try:
        send_frames(bus, frames, rate)
    finally:
        bus.shutdown()
    return 0


def run_guided(args):
    print("=" * 58)
    print(" V-IDS 보드 실측 테스트")
    print("=" * 58)
    print("\n보드가 켜져 있고 OLED에 V-IDS 화면이 떠 있어야 합니다.")
    print("아직이면 CubeIDE에서 Run(Ctrl+F11)으로 구운 뒤 다시 실행하세요.\n")

    normal, attack = choose_files()
    if normal is None:
        print("\n정상 데이터 CSV를 찾지 못했습니다.", file=sys.stderr)
        print("데이터셋을 이 스크립트와 같은 폴더에 두고 다시 실행하세요.", file=sys.stderr)
        return 1

    port = pick_port(args.port)
    if port is None:
        return 1
    bus = open_bus(port, args.baudrate, args.bitrate)
    if bus is None:
        return 1

    try:
        rate = normal["fps"] or FALLBACK_RATE
        print("\n" + "-" * 58)
        print(" [1/2] 정상 데이터 재생")
        print("-" * 58)
        describe(normal, 0, NORMAL_FRAMES)
        run_phase(bus, normal, 0, NORMAL_FRAMES, rate)

        print("\n  OLED 확인:")
        print("    FEAT / DET 두 줄에 숫자가 찍혀 있으면 성공입니다.")
        print("    ATK는 0이 정상입니다. 정상 데이터만 보냈습니다.")
        print("    W 는 RX 를 32로 나눈 값, RX + DRP 는 보낸 수와 비슷해야 합니다.")

        if attack is None:
            print("\n공격 데이터 CSV가 없어 1단계까지만 진행했습니다.")
            print("사진을 찍어서 보내주세요.")
            return 0

        if not wait_for_user(
            "사진을 찍은 뒤 보드의 리셋 버튼을 눌러주세요.\n"
            "리셋하지 않으면 측정값이 1단계와 섞입니다."
        ):
            return 1

        rate = attack["fps"] or rate
        print("\n" + "-" * 58)
        print(" [2/2] 공격 데이터 재생")
        print("-" * 58)
        skip = attack["skip"]
        print(f"  정상 {LEAD_FRAMES:,}프레임이 흐른 뒤 공격이 시작되는 지점을 골랐습니다.")
        print(f"  → 앞부분 윈도우 {LEAD_FRAMES // WINDOW_SIZE}개는 ATK가 0으로 유지되다가 올라갑니다.")
        if attack["training"]:
            print("  참고: 이 파일은 학습에도 쓴 파일입니다. 시연 촬영에는")
            print("        Pre_submit_* 같은 미사용 평가셋을 쓰는 편이 낫습니다.")
        describe(attack, skip, ATTACK_FRAMES)
        run_phase(bus, attack, skip, ATTACK_FRAMES, rate)

        print("\n  OLED 확인:")
        print("    이번에는 ATK가 0보다 커야 합니다.")
        print("    ATK는 경보가 켜져 있던 윈도우 수라 수백까지 올라갈 수 있습니다.")
        print("    FEAT의 min 값이 1단계보다 작아질 수 있는데 정상입니다.")
        print("\n사진을 찍어서 보내주세요. 두 장이면 끝입니다.")
    finally:
        bus.shutdown()
    return 0


def main():
    args = parse_args()
    if args.csv_path:
        return run_single(args)
    return run_guided(args)


if __name__ == "__main__":
    sys.exit(main())
