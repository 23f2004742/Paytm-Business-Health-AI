# Raspberry Pi 4B: shop-floor listener

The Pi is an **edge sensor**, not an AI box. It records short chunks of shop
conversation, decides cheaply whether anyone actually spoke, and posts the
audio to the backend. All the heavy work happens on the backend machine.

That split is deliberate. It is what keeps a Pi 4B viable, keeps the install
under a minute, and means a failing Pi degrades the product instead of
breaking it.

```
Microphone -> 10s WAV -> RMS voice gate -> POST /api/shop-intelligence/audio
                                                        |
                                          transcribe, extract, store
```

---

## 0. What you need

| | |
|---|---|
| Raspberry Pi 4B | any RAM size; 2 GB is plenty |
| Storage | the 16 GB pen drive or an SD card |
| Microphone | **any** USB mic, headset, or webcam with a mic |
| Network | Pi and backend machine on the same WiFi/LAN |

No specific microphone is assumed anywhere in this code. The input device is
configuration, not an assumption.

---

## 1. Install Raspberry Pi OS

Use **Raspberry Pi Imager** on your laptop.

1. Download from <https://www.raspberrypi.com/software/>
2. Choose device: **Raspberry Pi 4**
3. Choose OS: **Raspberry Pi OS Lite (64-bit)** — no desktop needed, and it
   leaves far more of a 16 GB drive for you
4. Choose storage: your 16 GB pen drive or SD card
5. Click the **gear icon** (or "Edit Settings") before writing and set:
   - hostname: `vyapaar-pi`
   - **Enable SSH**, with password authentication
   - username and password
   - **WiFi SSID and password** — do this here, it saves a lot of pain
   - locale/timezone
6. Write, then move the drive to the Pi and power on.

### Booting from the 16 GB pen drive

A Pi 4B can boot from USB, but only if its bootloader is recent enough.

- **Simplest path:** put Raspberry Pi OS on an SD card and use the pen drive
  for storage. Everything here needs well under 8 GB.
- **To boot from USB:** first boot once from an SD card and update the
  bootloader:
  ```bash
  sudo rpi-eeprom-update -a
  sudo reboot
  ```
  Then `sudo raspi-config` → *Advanced Options* → *Boot Order* → *USB Boot*.
  Shut down, remove the SD card, and boot from the pen drive.

> USB flash drives are slower and wear out faster than SD cards. Fine for this,
> but do not expect it to feel quick.

---

## 2. Connect over SSH

Find the Pi's address from your router, or:

```bash
ping vyapaar-pi.local
```

Then:

```bash
ssh pi@vyapaar-pi.local
# or
ssh pi@192.168.1.42
```

(SSH was enabled in step 1. If you skipped that: `sudo raspi-config` →
*Interface Options* → *SSH* → Enable.)

---

## 3. Connect the microphone

Plug it in **before** powering on if you can. Then:

```bash
arecord -l
```

Expected output:

```
**** List of CAPTURE Hardware Devices ****
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
```

`card 1` is your microphone. Nothing listed? See troubleshooting below.

Record five seconds and play it back:

```bash
arecord -D plughw:1,0 -f cd -d 5 test.wav
aplay test.wav
```

If that works, the operating system can hear you and the rest is configuration.

---

## 4. Install the client

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libportaudio2 git
```

`libportaudio2` is the one system package that matters. Without it
`sounddevice` imports but cannot open a device.

```bash
# copy the raspberry-pi/ folder to the Pi, e.g.
#   scp -r raspberry-pi pi@vyapaar-pi.local:~/vyapaar
cd ~/vyapaar

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-pi.txt
```

Three packages, a few MB, under a minute. No torch, no Whisper, no Ollama.

---

## 5. Configure

```bash
cp .env.example .env
nano .env
```

Two values matter:

### `BACKEND_URL`

The **LAN address of the backend machine**. Never `localhost` — on the Pi,
localhost is the Pi.

On the backend machine:

```bash
ipconfig                    # Windows: look for IPv4 Address
ip addr | grep "inet "      # macOS / Linux
```

```ini
BACKEND_URL=http://192.168.1.10:8000
```

Verify from the Pi before going further:

```bash
curl http://192.168.1.10:8000/health
```

> The backend must be started with `--host 0.0.0.0`, otherwise it only listens
> on its own loopback and the Pi cannot reach it. See the root README.

### `AUDIO_DEVICE`

```bash
python pi_client.py --list-devices
```

```
  [1] USB PnP Sound Device: Audio (hw:1,0)  (1 ch, 44100 Hz)
```

Set either the index or part of the name:

```ini
AUDIO_DEVICE=USB
```

**Prefer the name.** USB device indices shuffle between reboots; names do not.

---

## 6. Check everything before running

```bash
python pi_client.py --check
```

```
[1/3] Backend reachable...
      OK. Catalogue 292 items, 58 events stored.
[2/3] Audio input...
      OK. Using device 1.
[3/3] Local transcription...
      Disabled (Mode B: the backend transcribes). This is the default.

Result: READY
```

Test the microphone level on its own:

```bash
python audio_capture.py
```

It records one chunk and prints the RMS level. Below `0.001` is silence:
raise the input gain with `alsamixer` (press **F4** for capture, arrow up,
**Esc**).

---

## 7. Run

```bash
python pi_client.py
```

```
[19:24:07] [*] Listening. Press Ctrl+C to stop.
[19:24:18] [*] Heard: "Bhaiya Maggi hai? Nahi khatam ho gaya"
[19:24:18] [!] OUT OF STOCK: Maggi was asked for and is unavailable
               (confidence 97%). Potential lost sale.
```

Other modes:

```bash
python pi_client.py --once            # one chunk, then exit
python pi_client.py --demo            # no microphone; scripted transcripts
python pi_client.py --text "Bhaiya Maggi hai? Nahi khatam ho gaya"
```

`--demo` is the safety net: it proves the Pi, the network and the backend all
work without depending on the microphone.

---

## 8. Run it as a service (optional)

So it survives a reboot:

```bash
sudo nano /etc/systemd/system/vyapaar.service
```

```ini
[Unit]
Description=Paytm Vyapaar AI shop-floor listener
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/vyapaar
ExecStart=/home/pi/vyapaar/.venv/bin/python pi_client.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now vyapaar
journalctl -u vyapaar -f
```

---

## Two modes

### Mode B: edge sensor (default, recommended)

Pi records → sends WAV → **backend** transcribes and extracts.

The Pi stays cheap and cool. Requires `faster-whisper` on the backend
(`pip install -r backend/requirements-optional.txt`).

### Mode A: local transcription

Pi records → **Pi** transcribes → sends text.

Set `LOCAL_TRANSCRIPTION=true` and `pip install faster-whisper`.

Measured guidance for a Pi 4B:

| Model | Speed vs real time | Verdict |
|---|---|---|
| `tiny` | ~1.5–2.5x slower | usable for 10s chunks |
| `base` | ~3–4x slower | falls behind a live shop |
| `small` | ~6–8x slower | not viable |

A 10-second chunk taking 25 seconds to transcribe means the queue grows
forever. This is why Mode B is the default.

---

## Troubleshooting

### Microphone not detected

`arecord -l` shows nothing:

```bash
lsusb                     # is the device even enumerated?
dmesg | tail -20          # what happened when you plugged it in?
```

- Try a different USB port. **Use a USB 2.0 port (black), not USB 3.0 (blue)** —
  USB 3 ports emit interference in the 2.4 GHz band that also upsets WiFi, and
  some cheap mics simply do not enumerate on them.
- A mic drawing too much power on an unpowered hub will drop out. Plug it in
  directly.
- A headset with a single 4-pole jack will **not** work in the Pi's 3.5 mm
  socket: that socket is output only. Use USB.

### Permission denied on the audio device

```bash
sudo usermod -aG audio $USER
# log out and back in, then confirm:
groups
```

### "Cannot reach http://... " / backend unavailable

Work through it in order:

```bash
ping 192.168.1.10                          # 1. is the machine reachable?
curl http://192.168.1.10:8000/health       # 2. is the backend answering?
```

- Backend started with `--host 0.0.0.0`? Bound to `127.0.0.1` it is invisible
  to the Pi.
- Windows Firewall will block inbound port 8000 by default. Allow it:
  ```powershell
  New-NetFirewallRule -DisplayName "Vyapaar API" -Direction Inbound `
    -LocalPort 8000 -Protocol TCP -Action Allow
  ```
- Pi on 2.4 GHz and laptop on 5 GHz can land on isolated subnets on some
  routers. Check both addresses share a prefix.
- Many public and guest WiFi networks block device-to-device traffic entirely.
  Use a phone hotspot for the demo.

**The Pi does not lose data while this is happening.** Undeliverable chunks
spool to `spool/` and are sent when the link returns.

### Wrong IP address

The backend machine's DHCP lease changes and the Pi stops working overnight.
Either reserve the address on your router, or just re-check `ipconfig` before
demoing.

### Audio recording fails / empty or silent files

```bash
python audio_capture.py     # prints the RMS level
```

- RMS near zero: raise the capture gain in `alsamixer` (**F4**, arrow up).
- `Invalid sample rate`: some USB mics refuse 16 kHz. Set `SAMPLE_RATE=44100`
  in `.env` — the backend resamples.
- `Device unavailable`: something else holds the mic. `sudo fuser -v /dev/snd/*`

### Everything is being skipped as "Quiet"

The voice gate is too aggressive for your mic. Lower it:

```ini
VAD_RMS_THRESHOLD=0.005
```

Or turn it off entirely with `VAD_ENABLED=false` and let the backend decide.

### Nothing is extracted from clear speech

Check what the backend actually heard — the transcript is printed on the Pi
and shown in the dashboard's conversation feed. Usual causes:

- Whisper mis-transcribed a brand name. Add it to `PHONETIC_MAP` in
  `backend/app/services/shop_intelligence.py`.
- The product is not in `backend/data/catalog.json`. Add it.
- The exchange never said the product was missing. "Nahi hai" and "khatam ho
  gaya" are what mark something out of stock.

### It runs but the dashboard shows demo data

Events from the Pi land at the current wall-clock time. The dashboard shows
the seven days ending at the **dataset's** anchor date, so live events only
appear in the summary if that window includes today. Regenerate the dataset:

```bash
cd backend && python data/generate_data.py
```

To see raw live events regardless of the window:
`GET /api/shop-intelligence/events`.
