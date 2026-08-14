#include "can_bxcan.h"
#include "stm32f1xx_hal.h"

static can_rb_t *s_rb;
static CAN_HandleTypeDef *s_hcan;

static void dwt_cyccnt_init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;
}

float can_bxcan_now_seconds(void)
{
    return (float)DWT->CYCCNT / (float)SystemCoreClock;
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
    s_hcan = (CAN_HandleTypeDef *)hcan_handle;
    s_rb   = rb;

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
    CAN_RxHeaderTypeDef header;
    uint8_t data[8];

    if (HAL_CAN_GetRxMessage(hcan, CAN_RX_FIFO0, &header, data) != HAL_OK) {
        return;
    }

    can_frame_t frame;
    frame.arbitration_id = (uint16_t)header.StdId;
    frame.dlc            = (uint8_t)header.DLC;
    for (int i = 0; i < 8; i++) {
        frame.data[i] = (i < (int)header.DLC) ? data[i] : 0;
    }
    frame.timestamp = can_bxcan_now_seconds();

    can_rb_push(s_rb, &frame);
}
