memcheck
wait_any_key(){
    LAST_TIME=$(date +%s)
    echo "Press any key to continue..."
    while [ $? -eq 0 ]; do
        read -n1
        CURRENT_TIME=$(date +%s)
        ELAPSED_TIME=$((CURRENT_TIME - LAST_TIME))
        if [ $ELAPSED_TIME -ge 3 ]; then
            echo "Triggered!"
            break
        fi
    done
}

randomly_start_prts_last_call(){
    RANDOM_NUM=$((RANDOM % 10))
    if [ $RANDOM_NUM -eq 0 ]; then
        prts_last_call
        echo "........."
        sleep 3
        clear
        echo "Signal Lost...."
    fi
}

drain_stdin() {
    LAST_TIME=$(date +%s)
    echo "Draining stdin buffer..."
    while true; do
        read -n 1 -t 1
        CURRENT_TIME=$(date +%s)
        ELAPSED_TIME=$((CURRENT_TIME - LAST_TIME))
        if [ $ELAPSED_TIME -ge 3 ]; then
            echo "Done."
            break
        fi
    done
}

remount_sd(){
    umount /sd > /dev/null 2>&1
    umount /dev/mmcblk0p1 > /dev/null 2>&1

    mkdir /sd > /dev/null 2>&1
    mount -o iocharset=utf8 /dev/mmcblk0p1 /sd
    mount_ret=$?

    if [ $mount_ret -eq 0 ]; then
        echo "SD Card Mounted!"
        touch /tmp/sd_mounted
    else
        echo "No SD Card Found."
        rm -f /tmp/sd_mounted
    fi
}

remount_sd

# if epass_drm_app is not present
if [ ! -f "./epass_drm_app" ]; then
    cat << EOF
  _   _  ____  _____       _______
 | \\ | |/ __ \\|  __ \\   /\\|__   __|/\\
 |  \\| | |  | | |  | | /  \\  | |  /  \\
 | . \\ | |  | | |  | |/ /\\ \\ | | / /\\ \\
 | |\\  | |__| | |__| / ____ \\| |/ ____ \\
 |_| \\_|\\____/|_____/_/    \\_\\_/_/    \\_\\

Please copy 'epass_drm_app' and asset files.
to app directory.

EOF
    usbctl mtp
    return
fi

cat logo.txt
cat << EOF
---------------------------------------------
     RHODES ISLAND AUTHORIZATION PASS
   VERSION 1.0 (c) Ada.Closure.Church 1097
---------------------------------------------
EOF
echo -n -e "\\e[31m"
cat << EOF
   This pass certifies that the bearer is an
 authorized operator of Rhodes Island Co'Ltd.
  Unauthorized use of Rhodes Island property
            is strictly prohibited.
EOF
echo -n -e "\\e[0m"
cat << EOF
---------------------------------------------
EOF
sleep 1
echo -n -e "\\e[32m"
echo "Welcome to Rhodes Island!"
echo "You are in Terminal $(tty)."
echo "Access Level: Operator"
echo -n -e "\\e[0m"
echo ""
chmod +x ./epass_drm_app
./epass_drm_app version
cat /etc/os-release



while true; do
    chmod +x ./epass_drm_app
    if [ -f /tmp/sd_mounted ]; then
        ./epass_drm_app sd > /dev/null
    else
        ./epass_drm_app > /dev/null
    fi
    epass_ret=$?
    if [ $epass_ret -eq 1 ]; then
        remount_sd
        echo "Restarting..."
        sleep 2
    elif [ $epass_ret -eq 2 ]; then
        drain_stdin
        clear
        echo "Request application start..."
        chmod +x /tmp/appstart
        /tmp/appstart
        wait_any_key
        echo "Restarting..."
    elif [ $epass_ret -eq 3 ]; then
        randomly_start_prts_last_call
        poweroff
        return
    elif [ $epass_ret -eq 4 ]; then
        drain_stdin
        clear
        format_sd
        wait_any_key
        echo "Restarting..."
    elif [ $epass_ret -eq 5 ]; then
        drain_stdin
        clear
        mount_boot
        srgn_config
        wait_any_key
        echo "Restarting..."
    else
        break
    fi
done