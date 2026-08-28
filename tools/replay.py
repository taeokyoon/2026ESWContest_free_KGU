"""Car Hacking Challenge 데이터셋을 CAN 버스에 재생한다.

사용 예:
    python replay.py Pre_train_D_0.csv --port COM7
    python replay.py Pre_train_D_0.csv --port COM7 --limit 50000 --rate 2700
"""

import argparse
import csv
import sys
import time

import can


def parse_args():
    p = argparse.ArgumentParser(description="CAN 데이터셋 재생기")
    p.add_argument("csv_path", help="데이터셋 CSV 경로")
    p.add_argument("--port", default="COM7", help="USB-CAN 어댑터 포트 (기본 COM7)")
    p.add_argument("--bitrate", type=int, default=500000, help="CAN 비트레이트 (기본 500000)")
    p.add_argument("--baudrate", type=int, default=2000000, help="어댑터 시리얼 속도 (기본 2000000)")
    p.add_argument("--limit", type=int, default=20000, help="보낼 프레임 수 (0=전부, 기본 20000)")
    p.add_argument("--rate", type=float, default=0.0, help="초당 프레임 수 제한 (0=제한 없음)")
    p.add_argument("--skip", type=int, default=0, help="앞에서 건너뛸 프레임 수")
    return p.parse_args()


def available_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return "pyserial이 없습니다. pip install pyserial"

    ports = list(list_ports.comports())
    if not ports:
        return "연결된 시리얼 포트가 없습니다. 어댑터가 꽂혀 있는지 확인하세요."
    return "사용 가능한 포트:\n" + "\n".join(f"  {p.device}  {p.description}" for p in ports)


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


def main():
    args = parse_args()

    print(f"CSV 읽는 중: {args.csv_path}")
    frames = load_frames(args.csv_path, args.skip, args.limit)
    if not frames:
        print("보낼 프레임이 없습니다.", file=sys.stderr)
        return 1

    ids = {m.arbitration_id for m in frames}
    print(f"프레임 {len(frames):,}개 / 고유 ID {len(ids)}종류 / 윈도우 약 {len(frames)//32:,}개")

    try:
        bus = can.interface.Bus(
            interface="seeedstudio",
            channel=args.port,
            baudrate=args.baudrate,
            bitrate=args.bitrate,
        )
    except Exception as e:
        print(f"\n{args.port} 를 열지 못했습니다: {e}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    print(f"{args.port} 열림. 2초 후 시작합니다...")
    time.sleep(2)

    interval = 1.0 / args.rate if args.rate > 0 else 0.0
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
                print(f"  {sent:,} / {len(frames):,}  ({sent/elapsed:,.0f} fps)")
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        elapsed = time.perf_counter() - started
        bus.shutdown()

    print(f"\n완료: {sent:,}개 전송, {elapsed:.1f}초, 평균 {sent/elapsed:,.0f} fps")
    if args.rate > 0 and sent / elapsed < args.rate * 0.9:
        print("⚠️ 목표 속도에 못 미쳤습니다. PC나 어댑터가 병목입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
