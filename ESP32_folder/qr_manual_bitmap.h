// Precomputed QR matrix (ECC-L, version 3 = 29x29 modules) for:
//   https://labcoinremotemanual.pages.dev/
// Generated once with Python `qrcode` so the firmware needs no QR library.
#ifndef QR_MANUAL_BITMAP_H
#define QR_MANUAL_BITMAP_H

#include <stdint.h>

static const uint8_t QR_MANUAL_MODULES = 29;

// One uint32 per row; MS bit = column 0 (left). Unused low bits are zero.
static const uint32_t QR_MANUAL_ROW_BITS[29] = {
    534623359UL,  274470465UL,  391523677UL,  391820893UL, 390102109UL,
    273877569UL,  534074751UL,  616704UL,    432196399UL, 464351359UL,
    64224273UL,   404131115UL, 5614210UL,   201385087UL, 232532413UL,
    162619235UL,  357489026UL, 445201531UL, 89386245UL,  109750691UL,
    518098425UL,  1376017UL,   533210973UL, 274287378UL, 391826426UL,
    390148481UL,  390588943UL, 274381291UL, 534612330UL,
};

/** True when the module at (x,y) is dark — x,y in 0..QR_MANUAL_MODULES-1. */
static inline bool qrManualModuleDark(uint8_t x, uint8_t y) {
  if (x >= QR_MANUAL_MODULES || y >= QR_MANUAL_MODULES) {
    return false;
  }
  uint32_t row = QR_MANUAL_ROW_BITS[y];
  return ((row >> (QR_MANUAL_MODULES - 1 - x)) & 1U) != 0;
}

#endif  // QR_MANUAL_BITMAP_H
