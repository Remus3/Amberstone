// lane-widget/src/tray_icon.js
//
// The tray icon, inline. rc-shell has no Tray anywhere, so there is no in-repo
// precedent to copy and no icon asset to reuse - and committing a binary .png
// for a 16x16 glyph is not worth the repo weight or an ASCII-sweep exception.
// A base64 data URL is 7-bit ASCII, diffable, and loads with no file IO.
//
// The mark: three stacked "lane" bars of decreasing width on a transparent
// background. The top bar is the Arcane primary purple (#9646d9) and the lower
// two are the lavender-silver structural metal (#ad9dbd), matching the widget's
// own palette. Never gold - gold is not this theme's metal.
//
// Two sizes are supplied. Windows picks the 16px glyph for a standard-DPI
// taskbar and the 32px one when the shell scales; supplying only 16 makes a
// scaled tray look soft. Both are RGBA (colour type 6) so the corners stay
// genuinely transparent rather than keying against a taskbar colour.
//
// nativeImage is INJECTED rather than required here so this module stays
// importable (and greppable) outside electron. main.js passes it in.

"use strict";

// 16x16 RGBA PNG.
const TRAY_ICON_16_DATA_URL =
  "data:image/png;base64," +
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAO0lEQVR42mNgGD5g" +
  "mtvNnmluN/8TiXuob8DAg7Vz9/asnbv3Px7cQ1sDBkUY5K2du/cEGs6jnwFDFwAA" +
  "n36UAUvXzZ0AAAAASUVORK5CYII=";

// 32x32 RGBA PNG - the same mark at twice the scale.
const TRAY_ICON_32_DATA_URL =
  "data:image/png;base64," +
  "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAS0lEQVR42u3OOw0A" +
  "IAwAUdQhByWd2SqhErpjATWwM5EQEj73ktsvBACDHKvkWNumhIHzBwBTF1NviwkD" +
  "9w4App5MvUyWGHhvAPhOB1owWh/WBvy6AAAAAElFTkSuQmCC";

// Back-compat alias: the 16px glyph is the base image the tray is created from.
const TRAY_ICON_DATA_URL = TRAY_ICON_16_DATA_URL;

// Build a NativeImage from one data URL, or null when it cannot be decoded.
function imageFrom(nativeImage, dataUrl) {
  if (!nativeImage || typeof nativeImage.createFromDataURL !== "function") {
    return null;
  }
  try {
    const img = nativeImage.createFromDataURL(dataUrl);
    if (!img || (typeof img.isEmpty === "function" && img.isEmpty())) {
      return null;
    }
    return img;
  } catch (_e) {
    return null;
  }
}

// createTrayImage(nativeImage) -> a NativeImage, or null when it cannot be
// built. The 32px glyph is attached as a representation of the 16px base so the
// shell can pick the right one, and a failure to attach it is not fatal.
//
// A tray icon is cosmetic: failing to decode it must never stop the app from
// starting, so this never throws.
function createTrayImage(nativeImage) {
  const base = imageFrom(nativeImage, TRAY_ICON_16_DATA_URL);
  if (!base) {
    return null;
  }
  try {
    const big = imageFrom(nativeImage, TRAY_ICON_32_DATA_URL);
    if (big && typeof base.addRepresentation === "function") {
      base.addRepresentation({
        scaleFactor: 2,
        width: 32,
        height: 32,
        buffer: typeof big.toPNG === "function" ? big.toPNG() : undefined,
      });
    }
  } catch (_e) {
    // the 16px glyph alone is a perfectly good tray icon.
  }
  return base;
}

module.exports = {
  TRAY_ICON_DATA_URL,
  TRAY_ICON_16_DATA_URL,
  TRAY_ICON_32_DATA_URL,
  createTrayImage,
};
