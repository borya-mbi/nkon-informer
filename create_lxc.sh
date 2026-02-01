#!/bin/bash
# ==============================================================================
# Скрипт створення LXC контейнера для NKON Monitor
# ==============================================================================
# 
# Призначення: Автоматичне створення та налаштування LXC контейнера на Proxmox
#              для запуску NKON LiFePO4 Battery Monitor
#
# Автор:   NKON Monitor Project
# Версія:  1.0
#
# ==============================================================================
# ІНСТРУКЦІЯ ВИКОРИСТАННЯ:
# ==============================================================================
#
# 1. Скопіюйте цей файл на Proxmox хост:
#    scp create_lxc.sh root@PROXMOX_IP:/root/
#
# 2. SSH до Proxmox:
#    ssh root@PROXMOX_IP
#
# 3. Відредагуйте параметри у секції КОНФІГУРАЦІЯ (особливо PASSWORD!)
#    nano /root/create_lxc.sh
#
# 4. Зробіть скрипт виконуваним:
#    chmod +x /root/create_lxc.sh
#
# 5. Запустіть:
#    /root/create_lxc.sh
#
# 6. Слідуйте інструкціям на екрані
#
# ==============================================================================

set -e  # Зупинитися при помилці

# ==============================================================================
# КОНФІГУРАЦІЯ - ЗМІНІТЬ ЦІ ЗНАЧЕННЯ ПІД ВАШІ ПОТРЕБИ
# ==============================================================================

CTID=100                        # ID контейнера (100-999, змініть якщо зайнято)
HOSTNAME="nkon-monitor"         # Ім'я хоста
PASSWORD="ChangeMe123!"         # ⚠️ ОБОВ'ЯЗКОВО ЗМІНІТЬ НА БЕЗПЕЧНИЙ ПАРОЛЬ!

# Template (Ubuntu 22.04 LTS - рекомендовано)
TEMPLATE="local:vztmpl/ubuntu-22.04-standard_22.04-1_amd64.tar.zst"

# Ресурси
STORAGE="local-lvm"             # Storage для диска (local-lvm, local-zfs тощо)
RAM=512                         # RAM в MB
SWAP=512                        # Swap в MB
DISK=4                          # Disk в GB
CORES=1                         # CPU cores

# Мережа
BRIDGE="vmbr0"                  # Network bridge

# IP конфігурація - оберіть один з варіантів:
# ⚠️ РЕКОМЕНДАЦІЯ: Використовуйте статичний IP для production серверів!

# Варіант 1: DHCP (для тестування, простіше)
IP_CONFIG="ip=dhcp"

# Варіант 2: Статичний IP (РЕКОМЕНДОВАНО для серверів)
# Розкоментуйте наступний рядок та налаштуйте під вашу мережу:
# IP_CONFIG="ip=192.168.1.100/24,gw=192.168.1.1"
#
# Приклади:
# IP_CONFIG="ip=10.0.0.50/24,gw=10.0.0.1"       # Для мережі 10.0.0.0/24
# IP_CONFIG="ip=172.16.1.100/16,gw=172.16.0.1"  # Для мережі 172.16.0.0/16

# DNS сервери (Google DNS за замовчуванням)
DNS_NAMESERVER1="8.8.8.8"
DNS_NAMESERVER2="8.8.4.4"
# Або використовуйте ваші локальні DNS:
# DNS_NAMESERVER1="192.168.1.1"
# DNS_NAMESERVER2="1.1.1.1"  # Cloudflare DNS

# ==============================================================================
# ФУНКЦІЇ
# ==============================================================================

print_header() {
    echo "════════════════════════════════════════════════════════════"
    echo "  🚀 NKON Monitor LXC Container Creator"
    echo "════════════════════════════════════════════════════════════"
    echo ""
}

print_info() {
    echo "ℹ️  $1"
}

print_success() {
    echo "✅ $1"
}

print_error() {
    echo "❌ $1"
}

print_warning() {
    echo "⚠️  $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "Скрипт потрібно запускати від root!"
        echo "Спробуйте: sudo $0"
        exit 1
    fi
}

check_template() {
    print_info "Перевірка наявності template..."
    
    if pveam list local | grep -q "ubuntu-22.04-standard"; then
        print_success "Template знайдено"
        return 0
    fi
    
    print_warning "Template не знайдено, завантажую..."
    pveam download local ubuntu-22.04-standard_22.04-1_amd64.tar.zst
    
    if [ $? -eq 0 ]; then
        print_success "Template завантажено"
    else
        print_error "Не вдалося завантажити template"
        print_info "Спробуйте вручну: pveam available | grep ubuntu"
        exit 1
    fi
}

check_ctid() {
    print_info "Перевірка доступності CTID $CTID..."
    
    if pct status $CTID &>/dev/null; then
        print_error "CTID $CTID вже зайнято!"
        print_info "Доступні CTID:"
        pvesh get /cluster/resources --type vm | grep -o 'vmid":[0-9]*' | cut -d: -f2 | sort -n
        print_info "Змініть CTID у скрипті та спробуйте знову"
        exit 1
    fi
    
    print_success "CTID $CTID доступний"
}

check_password() {
    if [ "$PASSWORD" == "ChangeMe123!" ]; then
        print_warning "ВИ НЕ ЗМІНИЛИ СТАНДАРТНИЙ ПАРОЛЬ!"
        read -p "Бажаєте продовжити зі стандартним паролем? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            print_info "Відредагуйте скрипт і змініть PASSWORD"
            exit 1
        fi
    fi
}

create_container() {
    print_info "Створення LXC контейнера..."
    
    pct create $CTID $TEMPLATE \
        --hostname $HOSTNAME \
        --password $PASSWORD \
        --memory $RAM \
        --swap $SWAP \
        --cores $CORES \
        --rootfs $STORAGE:$DISK \
        --net0 name=eth0,bridge=$BRIDGE,$IP_CONFIG \
        --nameserver $DNS_NAMESERVER1 \
        --nameserver $DNS_NAMESERVER2 \
        --unprivileged 1 \
        --onboot 1 \
        --features nesting=1 \
        --description "NKON Monitor - LiFePO4 Battery Price Monitor"
    
    if [ $? -eq 0 ]; then
        print_success "Контейнер створено"
    else
        print_error "Помилка створення контейнера"
        exit 1
    fi
}

start_container() {
    print_info "Запуск контейнера..."
    
    pct start $CTID
    
    if [ $? -eq 0 ]; then
        print_success "Контейнер запущено"
        sleep 3  # Дати час на bootup
    else
        print_error "Помилка запуску контейнера"
        exit 1
    fi
}

print_summary() {
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  ✅ LXC контейнер успішно створено!"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "📋 Деталі контейнера:"
    echo "   • ID:       $CTID"
    echo "   • Hostname: $HOSTNAME"
    echo "   • Password: $PASSWORD"
    echo "   • RAM:      $RAM MB"
    echo "   • Disk:     $DISK GB"
    echo "   • CPU:      $CORES core(s)"
    echo "   • Bridge:   $BRIDGE"
    echo ""
    echo "🌐 Мережа:"
    if [[ "$IP_CONFIG" == *"dhcp"* ]]; then
        echo "   • Тип: DHCP"
        echo "   • IP адреса (може зайняти кілька секунд):"
        sleep 2
        pct exec $CTID -- ip -4 addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || echo "     DHCP ще не отримано, зачекайте..."
    else
        echo "   • Тип: Статичний IP"
        echo "   • Конфігурація: $IP_CONFIG"
    fi
    echo "   • DNS: $DNS_NAMESERVER1, $DNS_NAMESERVER2"
    echo ""
    echo "🔗 Підключення:"
    echo "   pct enter $CTID"
    echo ""
    echo "📊 Статус:"
    pct status $CTID
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "📖 Наступні кроки:"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "1. Підключіться до контейнера:"
    echo "   pct enter $CTID"
    echo ""
    echo "2. Встановіть залежності:"
    echo "   apt update && apt upgrade -y"
    echo "   apt install -y python3 python3-pip python3-venv git"
    echo ""
    echo "3. Встановіть Chrome:"
    echo "   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb"
    echo "   apt install -y ./google-chrome-stable_current_amd64.deb"
    echo ""
    echo "4. Дивіться повний гайд:"
    echo "   PROXMOX_DEPLOYMENT.md або DEPLOYMENT_CHECKLIST.md"
    echo ""
}

# ==============================================================================
# ОСНОВНА ПРОГРАМА
# ==============================================================================

main() {
    print_header
    
    # Перевірки
    check_root
    check_password
    check_ctid
    check_template
    
    # Створення
    create_container
    start_container
    
    # Результат
    print_summary
    
    print_success "Готово!"
}

# Запуск
main
