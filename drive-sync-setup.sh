#!/bin/bash
set -e
MOUNT_POINT="$HOME/drive-spectricom"
REMOTE_NAME="spectricom-drive"
DRIVE_FOLDER="Spectricom"
case "${1:-help}" in
install)
    echo "Installing rclone..."
    if command -v rclone &>/dev/null; then
        echo "✅ rclone already installed: $(rclone version | head -1)"
    else
        curl https://rclone.org/install.sh | sudo bash
        echo "✅ rclone installed"
    fi
    mkdir -p "$MOUNT_POINT"
    echo "✅ Mount point: $MOUNT_POINT"
    echo "Next: bash drive-sync-setup.sh auth";;
auth)
    echo "Configuring rclone for Google Drive..."
    if rclone listremotes | grep -q "$REMOTE_NAME:"; then
        read -p "Remote exists. Reconfigure? (y/N) " -n 1 -r; echo
        [[ ! $REPLY =~ ^[Yy]$ ]] && echo "Keeping config." && exit 0
        rclone config delete "$REMOTE_NAME"
    fi
    rclone config create "$REMOTE_NAME" drive scope "drive" root_folder_id "" --all
    echo "✅ Auth complete. Testing..."
    rclone lsd "$REMOTE_NAME:$DRIVE_FOLDER" 2>/dev/null && echo "✅ Can see Spectricom/" || echo "⚠️ Can't find Spectricom/"
    echo "Next: bash drive-sync-setup.sh mount";;
mount)
    mkdir -p "$MOUNT_POINT"
    fusermount -u "$MOUNT_POINT" 2>/dev/null || true
    rclone mount "$REMOTE_NAME:$DRIVE_FOLDER" "$MOUNT_POINT" --daemon \
        --vfs-cache-mode full --vfs-cache-max-age 1h --dir-cache-time 5s \
        --poll-interval 5s --vfs-write-back 0s \
        --log-file="$HOME/spectricom-orchestrator/logs/rclone.log" --log-level INFO
    sleep 2
    if mountpoint -q "$MOUNT_POINT"; then
        echo "✅ Mounted: $MOUNT_POINT"
        ls "$MOUNT_POINT/" 2>/dev/null
    else
        echo "❌ Mount failed. Check: tail -20 ~/spectricom-orchestrator/logs/rclone.log"
    fi;;
unmount) fusermount -u "$MOUNT_POINT" 2>/dev/null && echo "✅ Unmounted" || echo "Not mounted";;
test)
    mountpoint -q "$MOUNT_POINT" || { echo "❌ Not mounted"; exit 1; }
    echo "Checking folders..."
    for d in Registry Plans Logs Prompts Context Yorsie Yorsie/Briefs Yorsie/Design Yorsie/Synth Clinical Mini-Me Spikes Archive; do
        [ -d "$MOUNT_POINT/$d" ] && echo "  ✅ $d" || echo "  ❌ $d"
    done;;
symlink)
    mkdir -p "$HOME/spectricom-dev-pipeline/yorsie/briefs"
    ln -sfn "$MOUNT_POINT/Yorsie/Briefs" "$HOME/spectricom-dev-pipeline/yorsie/briefs-drive"
    echo "✅ ~/spectricom-dev-pipeline/yorsie/briefs-drive → Drive";;
autostart)
    if grep -q "Spectricom Drive" "$HOME/.bashrc" 2>/dev/null; then
        echo "Already in .bashrc"
    else
        echo -e "\n# Spectricom Drive auto-mount\nmountpoint -q $MOUNT_POINT 2>/dev/null || bash $HOME/spectricom-orchestrator/drive-sync-setup.sh mount 2>/dev/null" >> "$HOME/.bashrc"
        echo "✅ Auto-mount added to .bashrc"
    fi;;
status) mountpoint -q "$MOUNT_POINT" && echo "✅ Mounted" || echo "❌ Not mounted";;
*) echo "Commands: install | auth | mount | unmount | test | symlink | autostart | status"
    echo "Setup: install → auth → mount → test → symlink → autostart";;
esac
