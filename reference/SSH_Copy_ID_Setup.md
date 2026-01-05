# SSH Copy ID Setup Guide

`ssh-copy-id` is a standard command-line tool used to install your public SSH key on a remote server's `authorized_keys` file. This allows you to log in without a password.

## Prerequisites

Before using `ssh-copy-id`, ensure you have an SSH key pair generated on your local machine.

Check for existing keys:
```bash
ls -al ~/.ssh/id_*.pub
```

If you don't have one, generate a new pair:
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
# Follow the prompts (press Enter for default file location)
```

## Basic Usage

The basic syntax is:
```bash
ssh-copy-id user@hostname
```

**Example:**
```bash
ssh-copy-id ubuntu@192.168.1.10
```
*You will be prompted for the remote user's password one last time.*

## Common Options

### Specify a Port
If the remote SSH server runs on a non-standard port (default is 22):
```bash
ssh-copy-id -p 2222 user@hostname
```

### Specify a Specific Identity File
If you have multiple keys and want to copy a specific one (e.g., `id_rsa.pub` instead of default):
```bash
ssh-copy-id -i ~/.ssh/other_key.pub user@hostname
```

## Manual Method (If `ssh-copy-id` is unavailable)

If you cannot use `ssh-copy-id` (e.g., on Windows without WSL/Git Bash), you can manually append the key:

```bash
cat ~/.ssh/id_ed25519.pub | ssh user@hostname "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

## Troubleshooting

### Connection Refused (port 22)

If you see `connect to host ... port 22: Connection refused`, it means the client cannot reach the SSH service on the target.

**Possible Causes:**
1.  **SSH Server not installed/running:** Fresh Ubuntu installations (especially Desktop versions) might not have `openssh-server` installed or enabled by default.
2.  **Wrong IP Address:** Ensure `192.168.1.xxx` is actually the Pi's IP.
3.  **Firewall:** `ufw` or another firewall might be blocking port 22.

**Fixes (Run on the Raspberry Pi):**

1.  **Install/Start SSH:**
    ```bash
    sudo apt update
    sudo apt install openssh-server
    sudo systemctl enable --now ssh
    sudo systemctl status ssh  # Should say "active (running)"
    ```

2.  **Check IP Address:**
    ```bash
    ip addr show
    # Look for eth0 or wlan0 inet address
    ```

3.  **Allow SSH in Firewall:**
    ```bash
    sudo ufw allow ssh
    sudo ufw enable
    sudo ufw reload
    ```

## Verification

After copying the ID, try logging in:
```bash
ssh user@hostname
```
You should be logged in without being asked for a password.
