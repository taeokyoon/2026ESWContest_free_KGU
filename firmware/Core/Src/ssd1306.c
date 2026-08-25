#include "ssd1306.h"
#include <string.h>

void ssd1306_Reset(void) {
    /* I2C에서는 할 일 없음 */
}

void ssd1306_WriteCommand(uint8_t byte) {
    HAL_I2C_Mem_Write(&SSD1306_I2C_PORT, SSD1306_I2C_ADDR, 0x00, 1, &byte, 1, HAL_MAX_DELAY);
}

void ssd1306_WriteData(uint8_t* buffer, size_t buff_size) {
    HAL_I2C_Mem_Write(&SSD1306_I2C_PORT, SSD1306_I2C_ADDR, 0x40, 1, buffer, buff_size, HAL_MAX_DELAY);
}

static uint8_t SSD1306_Buffer[SSD1306_BUFFER_SIZE];
static SSD1306_t SSD1306;

SSD1306_Error_t ssd1306_FillBuffer(uint8_t* buf, uint32_t len) {
    SSD1306_Error_t ret = SSD1306_ERR;
    if (len <= SSD1306_BUFFER_SIZE) {
        memcpy(SSD1306_Buffer, buf, len);
        ret = SSD1306_OK;
    }
    return ret;
}

void ssd1306_Init(void) {
    ssd1306_Reset();
    HAL_Delay(100);

    ssd1306_SetDisplayOn(0);
    ssd1306_WriteCommand(0x20);
    ssd1306_WriteCommand(0x00);
    ssd1306_WriteCommand(0xB0);
    ssd1306_WriteCommand(0xC8);
    ssd1306_WriteCommand(0x00);
    ssd1306_WriteCommand(0x10);
    ssd1306_WriteCommand(0x40);
    ssd1306_SetContrast(0xFF);
    ssd1306_WriteCommand(0xA1);
    ssd1306_WriteCommand(0xA6);
    ssd1306_WriteCommand(0xA8);
    ssd1306_WriteCommand(0x3F);
    ssd1306_WriteCommand(0xA4);
    ssd1306_WriteCommand(0xD3);
    ssd1306_WriteCommand(0x00);
    ssd1306_WriteCommand(0xD5);
    ssd1306_WriteCommand(0xF0);
    ssd1306_WriteCommand(0xD9);
    ssd1306_WriteCommand(0x22);
    ssd1306_WriteCommand(0xDA);
    ssd1306_WriteCommand(0x12);
    ssd1306_WriteCommand(0xDB);
    ssd1306_WriteCommand(0x20);
    ssd1306_WriteCommand(0x8D);
    ssd1306_WriteCommand(0x14);
    ssd1306_SetDisplayOn(1);

    ssd1306_Fill(Black);
    ssd1306_UpdateScreen();

    SSD1306.CurrentX = 0;
    SSD1306.CurrentY = 0;
    SSD1306.Initialized = 1;
}

void ssd1306_Fill(SSD1306_COLOR color) {
    memset(SSD1306_Buffer, (color == Black) ? 0x00 : 0xFF, sizeof(SSD1306_Buffer));
}

void ssd1306_UpdateScreen(void) {
    for (uint8_t i = 0; i < SSD1306_HEIGHT / 8; i++) {
        ssd1306_WriteCommand(0xB0 + i);
        ssd1306_WriteCommand(0x00);
        ssd1306_WriteCommand(0x10);
        ssd1306_WriteData(&SSD1306_Buffer[SSD1306_WIDTH * i], SSD1306_WIDTH);
    }
}

void ssd1306_DrawPixel(uint8_t x, uint8_t y, SSD1306_COLOR color) {
    if (x >= SSD1306_WIDTH || y >= SSD1306_HEIGHT) {
        return;
    }
    if (color == White) {
        SSD1306_Buffer[x + (y / 8) * SSD1306_WIDTH] |= 1 << (y % 8);
    } else {
        SSD1306_Buffer[x + (y / 8) * SSD1306_WIDTH] &= ~(1 << (y % 8));
    }
}

char ssd1306_WriteChar(char ch, SSD1306_Font_t Font, SSD1306_COLOR color) {
    uint32_t i, b, j;

    if (ch < 32 || ch > 126)
        return 0;

    const uint8_t char_width = Font.char_width ? Font.char_width[ch - 32] : Font.width;

    if (SSD1306_WIDTH < (SSD1306.CurrentX + char_width) ||
        SSD1306_HEIGHT < (SSD1306.CurrentY + Font.height)) {
        return 0;
    }

    for (i = 0; i < Font.height; i++) {
        b = Font.data[(ch - 32) * Font.height + i];
        for (j = 0; j < char_width; j++) {
            if ((b << j) & 0x8000) {
                ssd1306_DrawPixel(SSD1306.CurrentX + j, (SSD1306.CurrentY + i), color);
            } else {
                ssd1306_DrawPixel(SSD1306.CurrentX + j, (SSD1306.CurrentY + i), (SSD1306_COLOR)!color);
            }
        }
    }

    SSD1306.CurrentX += char_width;
    return ch;
}

char ssd1306_WriteString(char* str, SSD1306_Font_t Font, SSD1306_COLOR color) {
    while (*str) {
        if (ssd1306_WriteChar(*str, Font, color) != *str) {
            return *str;
        }
        str++;
    }
    return *str;
}

void ssd1306_SetCursor(uint8_t x, uint8_t y) {
    SSD1306.CurrentX = x;
    SSD1306.CurrentY = y;
}

void ssd1306_SetContrast(const uint8_t value) {
    ssd1306_WriteCommand(0x81);
    ssd1306_WriteCommand(value);
}

void ssd1306_SetDisplayOn(const uint8_t on) {
    uint8_t value;
    if (on) {
        value = 0xAF;
        SSD1306.DisplayOn = 1;
    } else {
        value = 0xAE;
        SSD1306.DisplayOn = 0;
    }
    ssd1306_WriteCommand(value);
}

uint8_t ssd1306_GetDisplayOn(void) {
    return SSD1306.DisplayOn;
}
