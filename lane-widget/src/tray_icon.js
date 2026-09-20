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
// The taper is carried by WIDTH ALONE (12 / 9 / 6 px at 16, 24 / 17 / 12 at 32)
// and every bar body is fully opaque. Bar 3 used to be drawn at body alpha 200
// with alpha-110 end caps while bars 1 and 2 were body 255 / caps 140, which on
// a dark taskbar read as a rendering artefact rather than a deliberate third
// bar. All three bars now share body alpha 255 and cap alpha 140; the caps are
// the only translucent pixels and they exist to soften the bar ends.
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
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAM0lEQVR42mNgGD5g" +
  "mtvNnmluN/8TiXuob8DAg7Vz9/asnbv3Px7cQ1sDBm0Y9NDPgKELAO9UljE6Awkb" +
  "AAAAAElFTkSuQmCC";

// 32x32 RGBA PNG - the same mark at twice the scale.
const TRAY_ICON_32_DATA_URL =
  "data:image/png;base64," +
  "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAARklEQVR42u3Suw0A" +
  "IAwDUaZjOtd0GSEjMEimgZ4OISQ+9yT3VzglAIOSQyVH2zQRcH4A4FblVtviRMC9" +
  "AcDkCUXAewHAdzqfLWOnCwX99gAAAABJRU5ErkJggg==";

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
