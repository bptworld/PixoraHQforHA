# Pixora LED Studio — USB first installation

**Firmware 2.0.27 · Adafruit MatrixPortal S3 · 64×32 and 128×32**

[Download the USB first-install firmware](https://github.com/bptworld/PixoraHQforHA/raw/refs/heads/main/firmware/usb/2.0.27/pixora-v2.0.27-s3-first-install-usb.bin) · [SHA-256 checksum](SHA256SUMS.txt) · [Parts list](../../../pixora_led_displays/README.md#build-your-own-display)

One file supports both panel sizes. This is a complete **8 MB** flash image, installed at **0x0**.

> **First installation only:** this image overwrites all flash, including existing Wi-Fi, pairing and panel settings. Do not upload it through Studio's firmware update control. Use the separate user-OTA image for normal updates that preserve settings.

## USB installation on Windows

1. Connect the controller using a **USB-C data cable**. Close any serial monitor.
2. Install Python and esptool once:

   ```powershell
   py -m pip install esptool
   ```

3. Download the firmware above. Open PowerShell in the folder containing the downloaded file. Replace **COM4** with your controller's actual port:

   ```powershell
   $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
   py -m esptool --chip esp32s3 --port COM4 --baud 460800 write-flash --no-progress 0x0 pixora-v2.0.27-s3-first-install-usb.bin
   ```

4. Wait for esptool to report that the **data hash was verified**, then restart the controller. Keep USB power connected and the panel power wiring attached so the panel can show setup.

If the port cannot connect, hold **BOOT** while pressing and releasing **RESET**, then release **BOOT**. Select the USB port that appears and run the command again.

## First-time Wi-Fi setup

1. On a phone or computer, join the **Pixora-…** Wi-Fi network shown on the panel.
2. Enter the **eight-character setup password** shown on the second line.
3. Stay connected even if the phone says the network has no Internet.
4. Open **[http://192.168.4.1](http://192.168.4.1)** in a browser.
5. Enter the exact name and password of your **2.4 GHz home Wi-Fi**.
6. Select **64×32** or **128×32**, then press **Save Wi-Fi**. The controller restarts.
7. Reconnect your phone or computer to home Wi-Fi. Add the display in **Pixora LED Studio** within Home Assistant using its displayed IP address.

## Home Assistant app

Install Pixora LED Studio from the [PixoraHQ for Home Assistant repository](https://github.com/bptworld/PixoraHQforHA).

## Verification

Application bytes match the existing tested 2.0.27 OTA image. Boot components, offsets, the blank settings partition and SHA-256 have been checked locally. No private firmware source or Wi-Fi credentials are included.
