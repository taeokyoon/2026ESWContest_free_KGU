#ifndef INC_SSD1306_CONF_H_
#define INC_SSD1306_CONF_H_

#define STM32F1

#define SSD1306_USE_I2C

#define SSD1306_I2C_PORT        hi2c1
#define SSD1306_I2C_ADDR        (0x3C << 1)

#define SSD1306_HEIGHT          64
#define SSD1306_WIDTH           128

#define SSD1306_INCLUDE_FONT_6x8
#define SSD1306_INCLUDE_FONT_7x10

#endif
