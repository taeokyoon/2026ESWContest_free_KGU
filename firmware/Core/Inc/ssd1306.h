#ifndef INC_SSD1306_H_
#define INC_SSD1306_H_

#include <stddef.h>
#include <stdint.h>

#include "ssd1306_conf.h"
#include "stm32f1xx_hal.h"

#ifndef SSD1306_BUFFER_SIZE
#define SSD1306_BUFFER_SIZE SSD1306_WIDTH * SSD1306_HEIGHT / 8
#endif

extern I2C_HandleTypeDef SSD1306_I2C_PORT;

typedef enum {
    Black = 0x00,
    White = 0x01
} SSD1306_COLOR;

typedef enum {
    SSD1306_OK = 0x00,
    SSD1306_ERR = 0x01
} SSD1306_Error_t;

typedef struct {
    uint16_t CurrentX;
    uint16_t CurrentY;
    uint8_t Initialized;
    uint8_t DisplayOn;
} SSD1306_t;

typedef struct {
    const uint8_t width;
    const uint8_t height;
    const uint16_t *const data;
    const uint8_t *const char_width;
} SSD1306_Font_t;

void ssd1306_Init(void);
void ssd1306_Fill(SSD1306_COLOR color);
void ssd1306_UpdateScreen(void);
void ssd1306_DrawPixel(uint8_t x, uint8_t y, SSD1306_COLOR color);
char ssd1306_WriteChar(char ch, SSD1306_Font_t Font, SSD1306_COLOR color);
char ssd1306_WriteString(char* str, SSD1306_Font_t Font, SSD1306_COLOR color);
void ssd1306_SetCursor(uint8_t x, uint8_t y);
void ssd1306_SetContrast(const uint8_t value);
void ssd1306_SetDisplayOn(const uint8_t on);
uint8_t ssd1306_GetDisplayOn(void);

void ssd1306_Reset(void);
void ssd1306_WriteCommand(uint8_t byte);
void ssd1306_WriteData(uint8_t* buffer, size_t buff_size);
SSD1306_Error_t ssd1306_FillBuffer(uint8_t* buf, uint32_t len);

#endif
