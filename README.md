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
You cannot reach your MacBook from the internet with normal port forwarding. Use one of these:
- Ask your carrier for a public IPv4 address (sometimes called a "routable" or "static" IP).
- Use IPv6 if your carrier provides it and open the correct ports.
- Use a tunnel service (examples: Tailscale, ZeroTier, Cloudflare Tunnel).
- Use a small VPS and a reverse SSH tunnel.

If you only need access inside your home network, CGNAT is not a problem.

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
