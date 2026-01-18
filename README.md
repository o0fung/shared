# Headless MacBook Home Server (Terminal Guide)

This guide shows how to set up an old MacBook to run as a home web server without opening the lid after setup. All steps use Terminal and are written for beginners.

## What you need
- MacBook and power adapter
- Another computer or phone on the same network (for remote access)
- External monitor or HDMI dummy plug (needed for lid-closed operation)
- Ethernet cable (optional but more stable than Wi-Fi)

## Step 1: Open Terminal
Open Terminal on the MacBook. You will copy and paste the commands in each step.

## Step 2: Check macOS version and update (recommended)
Check your macOS version:

```
sw_vers
```

List available updates:

```
softwareupdate --list
```

Install all updates and reboot if needed:

```
sudo softwareupdate --install --all --restart
```

## Step 3: Set power and wake behavior (stay on when plugged in)
These settings stop the MacBook from sleeping on power and make it restart after power loss.

```
sudo systemsetup -setrestartpowerfailure on
sudo systemsetup -setwakeonnetworkaccess on
sudo pmset -c sleep 0
sudo pmset -c displaysleep 0
sudo pmset -c disksleep 0
sudo pmset -a powernap 1
```

Check the current settings:

```
pmset -g custom
```

## Step 4: Enable SSH (remote login)
This lets you manage the MacBook without opening the lid.

```
sudo systemsetup -setremotelogin on
sudo systemsetup -getremotelogin
```

Find your current IP address:

```
networksetup -listallhardwareports
ipconfig getifaddr en0
ipconfig getifaddr en1
```

Tip: `en0` is usually Wi-Fi or Ethernet. Use the one that returns an IP.

## Step 5: Give the MacBook a stable IP address
A stable IP makes it easier to reach your server.

### Option A (recommended): Router DHCP reservation
This is done in your router settings, not in Terminal. It keeps the IP stable without changing anything on the MacBook.

### Option B (Terminal-only): Set a static IP on the MacBook
Replace the values below with your own network details.

```
sudo networksetup -setmanual "Wi-Fi" 192.168.1.50 255.255.255.0 192.168.1.1
sudo networksetup -setdnsservers "Wi-Fi" 1.1.1.1 8.8.8.8
```

If you use Ethernet instead of Wi-Fi, replace "Wi-Fi" with "Ethernet".

## Step 6: Check why your IP looks different (CGNAT / double NAT)
It is normal to see two different IP addresses:
- Your MacBook has a private IP inside your home network.
- A website shows your public IP on the internet.

With 5G routers, the router can also be behind the carrier's network (CGNAT). In that case, port forwarding will not work from the internet.

### 1) Find your local IP (private IP)
```
ipconfig getifaddr en0
ipconfig getifaddr en1
```

### 2) Find your public IP (internet IP)
```
curl -4 https://ifconfig.me
```

### 3) Find your router gateway IP (to log in)
```
route -n get default
```
Look for the line that says `gateway:`. Open `http://GATEWAY_IP` in your browser and log in to the router. Find the "WAN IP" or "Internet IP".

### 4) Compare the WAN IP to the public IP
- If they match, you likely have a public IP.
- If they do not match, or if the WAN IP starts with `10.`, `192.168.`, `172.16-31.`, or `100.64-127.`, you are behind another NAT (CGNAT).

### What to do if you are behind CGNAT
You cannot reach your MacBook from the internet with normal port forwarding. Use one of the options below. If you only need access inside your home network, CGNAT is not a problem.

### Free options (no public IP required)
These work well for home use and are beginner friendly.

#### Option A: Tailscale (free personal plan)
Tailscale creates a private network between your devices.

On the MacBook (server):
1. Install Tailscale:
```
brew install --cask tailscale
```
2. Open the Tailscale app once so macOS can approve it:
```
open -a Tailscale
```
3. Sign in in the app window, then bring it up in Terminal:
```
tailscale up
```
4. Get the Tailscale IP:
```
tailscale ip -4
```

On your other device (client):
1. Install Tailscale and sign in with the same account.
2. Use the Tailscale IP to connect:
```
ssh YOUR_USER@TAILSCALE_IP
```
3. Open the web server from that device:
```
http://TAILSCALE_IP:8080
```

#### Option B: Cloudflare Tunnel (free)
This creates a public URL without port forwarding.

How it works (plain language):
- `cloudflared` opens an outbound encrypted tunnel from your MacBook to Cloudflare.
- Cloudflare gives you a public URL and forwards requests through that tunnel.
- No inbound port forwarding is needed, which is why it works behind CGNAT.

When you can access your server:
- Quick tunnel: immediately after the command prints a `trycloudflare.com` URL, and only while that Terminal window is running.
- Stable tunnel: after the DNS route is created and the tunnel is running. DNS updates can take a few minutes to propagate.

Quick temporary tunnel (no account, changes each time):
```
brew install cloudflared
cloudflared tunnel --url http://localhost:8080
```
Cloudflared prints a `trycloudflare.com` URL. Open that URL from anywhere.

Stable tunnel (requires a free Cloudflare account and domain):
1. Install cloudflared:
```
brew install cloudflared
```
2. Login and authorize:
```
cloudflared tunnel login
```
3. Create a named tunnel:
```
cloudflared tunnel create macbook-server
```
4. Create a config file:
```
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<EOF
tunnel: macbook-server
credentials-file: /Users/YOUR_USER/.cloudflared/macbook-server.json

ingress:
  - hostname: server.example.com
    service: http://localhost:8080
  - service: http_status:404
EOF
```
Replace `YOUR_USER` and `server.example.com` with your values.
5. Route the hostname to the tunnel:
```
cloudflared tunnel route dns macbook-server server.example.com
```
6. Run the tunnel:
```
cloudflared tunnel run macbook-server
```

Optional script (stable tunnel):
Save this as `~/bin/start-cloudflared-tunnel.sh`, then run it when you want the tunnel online.
```
mkdir -p ~/bin
cat > ~/bin/start-cloudflared-tunnel.sh <<'EOF'
#!/bin/bash
set -euo pipefail

TUNNEL_NAME="macbook-server"
LOG_FILE="$HOME/cloudflared.log"

cloudflared tunnel run "$TUNNEL_NAME" --loglevel info --logfile "$LOG_FILE"
EOF

chmod +x ~/bin/start-cloudflared-tunnel.sh
```
Run it:
```
~/bin/start-cloudflared-tunnel.sh
```

#### Option C: ZeroTier (free tier)
ZeroTier is similar to Tailscale but uses a manual network ID.

On the MacBook:
1. Install:
```
brew install --cask zerotier-one
```
2. Join your network (replace with your ID):
```
sudo zerotier-cli join YOUR_NETWORK_ID
```
3. Approve the MacBook in the ZeroTier web console.

On your other device:
1. Install ZeroTier and join the same network ID.
2. Use the assigned ZeroTier IP to connect.

### Paid or advanced options
Use these if you want a public IP or need a stable public URL.

#### Option D: Ask the carrier for a public IPv4 or static IP
1. Contact your 5G carrier and request a public IPv4 address.
2. After they enable it, compare WAN IP and public IP again (Step 6).
3. Then you can use normal port forwarding on your router.

#### Option E: VPS reverse SSH tunnel
This uses a small cloud server with a public IP.

1. Rent a small VPS (any provider is fine).
2. On the VPS, allow SSH and the port you will use (for example 8080).
3. From the MacBook, create an SSH tunnel:
```
ssh -N -R 8080:localhost:8080 YOUR_VPS_USER@YOUR_VPS_IP
```
4. Visit `http://YOUR_VPS_IP:8080` from anywhere.
5. To keep it running after disconnects, install autossh:
```
brew install autossh
autossh -M 0 -N -R 8080:localhost:8080 YOUR_VPS_USER@YOUR_VPS_IP
```

## Step 7: Install Homebrew (package manager)
Check if Homebrew is installed:

```
brew --version
```

If you see "command not found", install it:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Step 8: Install a simple web server (Caddy)
Caddy is easy for beginners and works well for a home server.

Create a simple site folder and test file:

```
mkdir -p "$HOME/Sites/home-server"
echo "It works." > "$HOME/Sites/home-server/index.html"
```

Install Caddy:

```
brew install caddy
```

Create a basic Caddy config file:

```
sudo mkdir -p /etc/caddy
sudo /bin/sh -c 'cat > /etc/caddy/Caddyfile <<EOF
:8080
root * '"$HOME"'/Sites/home-server
file_server
EOF'
```

Start Caddy at boot (system service):

```
sudo brew services start caddy
```

Check service status:

```
sudo brew services list
```

Test locally:

```
curl http://localhost:8080
```

## Step 9: Allow the server through the macOS firewall
Turn on the firewall (safe to run even if already on):

```
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
```

Allow Caddy:

```
CADDY_BIN="$(which caddy)"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$CADDY_BIN"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$CADDY_BIN"
```

## Step 10: Run with the lid closed (clamshell mode)
MacBooks sleep when the lid is closed unless in clamshell mode.

1. Connect power.
2. Connect an external display or HDMI dummy plug.
3. Wake the MacBook.
4. Close the lid.

Verify it is still awake from another device:

```
ssh YOUR_USER@YOUR_MACBOOK_IP
curl http://YOUR_MACBOOK_IP:8080
```

## Step 11: Basic control commands
Restart the web server:

```
sudo brew services restart caddy
```

Stop the web server:

```
sudo brew services stop caddy
```

## Troubleshooting (quick checks)
- Server not reachable: check IP, firewall, and that Caddy is running.
- Mac sleeps when lid is closed: you must use clamshell mode with power and external display or HDMI dummy.
- Web page not loading: run `curl http://localhost:8080` on the MacBook to confirm local access.

## Safety notes
- Keep airflow around the MacBook to avoid overheating.
- Use Ethernet if you can.
- Consider a small UPS or smart plug for remote recovery.
