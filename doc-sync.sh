#!/bin/bash
set -e
MOUNT="$HOME/drive-spectricom"
DL="/mnt/c/Users/gkass/Downloads"
route() {
    case "$1" in
        Spectricom_Document_Registry*) echo "Registry";;
        Spectricom_Parallel_Dev_Master*) echo "Plans";;
        spectricom-orchestrator-arch*) echo "Plans";;
        Spectricom_Logs*) echo "Logs";;
        Gemma_System_Prompt*) echo "Prompts";;
        spectricom-context-slim*) echo "Context";;
        yorsie-design-system*|yorsie-your-intel*|yorsie-bug-registry*|yorsie-compact-feature*) echo "Yorsie/Design";;
        toni-batch*) echo "Yorsie/Briefs";;
        yorsie-synth*|yorsie-food-synth*) echo "Yorsie/Synth";;
        SPIKE-*) echo "Spikes";;
        *) echo "";;
    esac
}
case "${1:-help}" in
push)
    mountpoint -q "$MOUNT" || { echo "❌ Not mounted"; exit 1; }
    echo "Pushing docs → Drive..."; c=0
    for f in "$DL"/Spectricom_*.md "$DL"/spectricom-*.md "$DL"/Gemma_System_Prompt*.md "$DL"/yorsie-*.md "$DL"/toni-batch-*.md "$DL"/SPIKE-*.md; do
        [ -f "$f" ] || continue; n=$(basename "$f"); d=$(route "$n")
        [ -z "$d" ] && continue
        mkdir -p "$MOUNT/$d"; cp "$f" "$MOUNT/$d/$n"
        echo "  ✅ $n → $d/"; c=$((c+1))
    done; echo "✅ $c files pushed";;
pull)
    mountpoint -q "$MOUNT" || { echo "❌ Not mounted"; exit 1; }
    echo "Pulling latest → Downloads..."
    for dir in Registry Plans Logs Prompts Context; do
        for f in "$MOUNT/$dir"/*.md; do
            [ -f "$f" ] || continue; cp "$f" "$DL/$(basename "$f")"
            echo "  ✅ $(basename "$f") ← $dir/"
        done
    done; echo "✅ Done";;
list)
    mountpoint -q "$MOUNT" || { echo "❌ Not mounted"; exit 1; }
    for d in Registry Plans Logs Prompts Context Yorsie/Design Yorsie/Briefs Yorsie/Synth Clinical Mini-Me Spikes Archive; do
        c=$(ls "$MOUNT/$d" 2>/dev/null | wc -l)
        echo "  📁 $d ($c files)"
    done;;
*) echo "Commands: push | pull | list";;
esac
