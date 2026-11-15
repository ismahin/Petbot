#pragma once
#define LGFX_USE_V1
#include <LovyanGFX.hpp>
#include "Settings.hpp"

class PetDisplay : public lgfx::LGFX_Device {
    lgfx::Bus_SPI bus_;
    lgfx::Panel_ST7789 panel_;
public:
    PetDisplay() {
        auto bus = bus_.config();
        bus.spi_host = SPI2_HOST;
        bus.spi_mode = 0;
        bus.freq_write = settings::spiHz;
        bus.freq_read = 16000000;
        bus.spi_3wire = false;
        bus.use_lock = true;
        bus.dma_channel = SPI_DMA_CH_AUTO;
        bus.pin_sclk = settings::tftSck;
        bus.pin_mosi = settings::tftMosi;
        bus.pin_miso = -1;
        bus.pin_dc = settings::tftDc;
        bus_.config(bus);
        panel_.setBus(&bus_);
        auto panel = panel_.config();
        panel.pin_cs = settings::tftCs;
        panel.pin_rst = settings::tftReset;
        panel.pin_busy = -1;
        panel.panel_width = panel.memory_width = 240;
        panel.panel_height = panel.memory_height = 320;
        panel.offset_x = panel.offset_y = panel.offset_rotation = 0;
        panel.readable = false;
        panel.invert = settings::panelInvert;
        panel.rgb_order = settings::panelRgbOrder;
        panel.bus_shared = false; // SD is held inactive.
        panel_.config(panel);
        setPanel(&panel_);
    }
};
