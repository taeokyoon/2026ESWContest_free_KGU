#include "can_bxcan.h"
#include "stm32f1xx_hal.h"

#define CAN_BXCAN_CYC_PER_US 72u
#define CAN_BXCAN_STDID_MAX  0x7FFu

static can_rb_t *s_rb;
static CAN_HandleTypeDef *s_hcan;

static volatile uint32_t s_cyc_last;
static volatile uint32_t s_cyc_rem;
static volatile uint64_t s_us_total;
static volatile uint32_t s_rejected;

static void dwt_cyccnt_init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;

    s_cyc_last = 0u;
    s_cyc_rem  = 0u;
    s_us_total = 0u;
}

static uint64_t time_advance_locked(void)
{
    uint32_t now   = DWT->CYCCNT;
    uint32_t delta = now - s_cyc_last;

    s_cyc_last  = now;
    s_us_total += delta / CAN_BXCAN_CYC_PER_US;
    s_cyc_rem  += delta % CAN_BXCAN_CYC_PER_US;

    if (s_cyc_rem >= CAN_BXCAN_CYC_PER_US) {
        s_cyc_rem  -= CAN_BXCAN_CYC_PER_US;
        s_us_total += 1u;
    }
    return s_us_total;
}

static uint64_t time_now_us(void)
{
    uint32_t primask = __get_PRIMASK();
    uint64_t us;

    __disable_irq();
    us = time_advance_locked();
    __set_PRIMASK(primask);
    return us;
}

void can_bxcan_time_service(void)
{
    (void)time_now_us();
}

float can_bxcan_now_seconds(void)
{
    return (float)time_now_us() * 1e-6f;
}

uint32_t can_bxcan_rejected(void)
{
    return s_rejected;
}

static int can_config_filter(CAN_HandleTypeDef *hcan)
{
    CAN_FilterTypeDef f = {0};
    f.FilterBank           = 0;
    f.FilterMode           = CAN_FILTERMODE_IDMASK;
    f.FilterScale          = CAN_FILTERSCALE_32BIT;
    f.FilterIdHigh         = 0x0000;
    f.FilterIdLow          = 0x0000;
    f.FilterMaskIdHigh     = 0x0000;
    f.FilterMaskIdLow      = 0x0000;
    f.FilterFIFOAssignment = CAN_RX_FIFO0;
    f.FilterActivation     = ENABLE;
    f.SlaveStartFilterBank = 14;
    return (HAL_CAN_ConfigFilter(hcan, &f) == HAL_OK) ? 0 : -1;
}

int can_bxcan_start(void *hcan_handle, can_rb_t *rb)
{
    s_hcan     = (CAN_HandleTypeDef *)hcan_handle;
    s_rb       = rb;
    s_rejected = 0u;

    s_hcan->Init.Prescaler     = 9;
    s_hcan->Init.Mode          = CAN_MODE_SILENT;
    s_hcan->Init.SyncJumpWidth = CAN_SJW_1TQ;
    s_hcan->Init.TimeSeg1      = CAN_BS1_6TQ;
    s_hcan->Init.TimeSeg2      = CAN_BS2_1TQ;
    s_hcan->Init.TimeTriggeredMode    = DISABLE;
    s_hcan->Init.AutoBusOff           = DISABLE;
    s_hcan->Init.AutoWakeUp           = DISABLE;
    s_hcan->Init.AutoRetransmission   = DISABLE;
    s_hcan->Init.ReceiveFifoLocked    = DISABLE;
    s_hcan->Init.TransmitFifoPriority = DISABLE;

    if (HAL_CAN_Init(s_hcan) != HAL_OK)      return -1;
    if (can_config_filter(s_hcan) != 0)      return -2;

    dwt_cyccnt_init();

    if (HAL_CAN_ActivateNotification(s_hcan, CAN_IT_RX_FIFO0_MSG_PENDING) != HAL_OK) return -3;
    if (HAL_CAN_Start(s_hcan) != HAL_OK)     return -4;
    return 0;
}

void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
{
    CAN_RxHeaderTypeDef header = {0};
    uint8_t data[8] = {0};
    can_frame_t frame;
    uint8_t dlc;

    if (hcan != s_hcan) {
        return;
    }
    if (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &header, data) != HAL_OK) {
        return;
    }
    if (header.IDE != CAN_ID_STD ||
        header.RTR != CAN_RTR_DATA ||
        header.StdId > CAN_BXCAN_STDID_MAX) {
        s_rejected++;
        return;
    }

    dlc = (header.DLC > 8u) ? 8u : (uint8_t)header.DLC;

    frame.arbitration_id = (uint16_t)header.StdId;
    frame.dlc            = dlc;
    for (int i = 0; i < 8; i++) {
        frame.data[i] = (i < (int)dlc) ? data[i] : 0;
    }
    frame.timestamp = can_bxcan_now_seconds();

    can_rb_push(s_rb, &frame);
}
