# Browser USB bundle

`display_usb_entry.js` wraps Espressif esptool-js 0.5.7. The checked-in `pixora_led_displays/display_usb.js` is bundled with esbuild 0.25.12, includes the S3 flashing stub, and makes no CDN requests. Licenses ship with the app. No firmware source is included.

Install build dependencies in a temporary directory on D: and run esbuild with that directory’s esptool-js entry as an alias:

```powershell
npm install --prefix D:/planner/.build-tmp/led-installer-tools esptool-js@0.5.7 esbuild@0.25.12
D:/planner/.build-tmp/led-installer-tools/node_modules/.bin/esbuild.cmd tools/display_usb_entry.js --bundle --format=esm --minify --outfile=pixora_led_displays/display_usb.js --alias:esptool-js=D:/planner/.build-tmp/led-installer-tools/node_modules/esptool-js/lib/index.js
```

Run `node tests/led_display_usb_check.mjs` and the installer browser regression after rebuilding. Tracing must remain disabled because serial packets contain configured Wi-Fi and pairing data. The installed flash checksum must match before a success reset.
