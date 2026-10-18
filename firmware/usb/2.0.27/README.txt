Pixora LED Studio - USB first installation - 2.0.27

Hardware: Adafruit MatrixPortal S3, 64x32 or 128x32 (two 64x32 panels).
One file supports both sizes. This is a complete 8MB flash image, flashed at 0x0.
FIRST INSTALL ONLY: overwrites all flash, including old Wi-Fi, pairing and panel
settings. Do not upload this file through LED Studio's firmware update control.
Use the separate user-OTA image for normal updates that preserve settings.

USB installation on Windows
1. Connect the controller with a USB data cable. Close any serial monitor.
2. Install Python and esptool (once):
   py -m pip install esptool
3. Open PowerShell in this folder. Replace COM4 with the controller's actual port:
   $env:PYTHONUTF8='1'; $env:PYTHONIOENCODING='utf-8'
   py -m esptool --chip esp32s3 --port COM4 --baud 460800 write-flash --no-progress 0x0 pixora-v2.0.27-s3-first-install-usb.bin
4. Wait for esptool to report that the data hash was verified, then restart the
   controller. Keep normal panel power connected so the LED panel can show setup.
   If the port cannot connect, hold BOOT while pressing/releasing RESET, release
   BOOT, then select the USB port that appears and run the command again.

First-time Wi-Fi setup
1. On a phone or computer, join the Pixora-... Wi-Fi network shown on the panel.
2. Enter the eight-character setup password shown on the second line.
3. Stay connected even if the phone says the network has no Internet.
4. Open http://192.168.4.1 in a browser.
5. Enter the exact name and password of your 2.4GHz home Wi-Fi.
6. Select 64x32 or 128x32 and press Save Wi-Fi. The controller restarts.
7. Reconnect your phone/computer to home Wi-Fi. Add the display in Pixora LED
   Studio within Home Assistant using its displayed IP address.

HA apps repository: https://github.com/bptworld/PixoraHQforHA

Verification: application bytes match the existing tested 2.0.27 OTA image.
Boot components/offsets, blank settings partition and SHA-256 checked locally.
No private firmware source or Wi-Fi credentials are included.
