#!/usr/bin/env bash
# Установка Protégé 5.5.0 в Linux Mint.
# Почему 5.5.0, а не новее: в 5.6.x вкладка SPARQL Query открывается пустой (ошибка плагина),
# а в 5.5.0 она работает. Java уже встроена в архив — ставить её отдельно не нужно.
set -e

VER="5.5.0"
URL="https://github.com/protegeproject/protege-distribution/releases/download/v${VER}/Protege-${VER}-linux.tar.gz"
DL="$HOME/Downloads"
INSTALL_DIR="$HOME/protege"

echo "==> 1/5 Скачиваю Protégé ${VER} (~125 МБ)..."
mkdir -p "$DL"
cd "$DL"
wget -c "$URL" -O "Protege-${VER}-linux.tar.gz"

echo "==> 2/5 Распаковываю..."
tar -xzf "Protege-${VER}-linux.tar.gz"

echo "==> 3/5 Переношу в ${INSTALL_DIR}..."
rm -rf "$INSTALL_DIR"
mv "Protege-${VER}" "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/run.sh" "$INSTALL_DIR/jre/bin/java"
# даём программе больше памяти (по умолчанию всего 500 МБ)
sed -i 's/-Xmx500M/-Xmx2G/' "$INSTALL_DIR/run.sh"

echo "==> 4/5 Создаю команду 'protege' для терминала..."
mkdir -p "$HOME/.local/bin"
ln -sf "$INSTALL_DIR/run.sh" "$HOME/.local/bin/protege"

echo "==> 5/5 Добавляю ярлык в меню..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/protege.desktop" <<EOF
[Desktop Entry]
Name=Protégé
GenericName=Редактор онтологий
Exec=${INSTALL_DIR}/run.sh
Path=${INSTALL_DIR}
Icon=${INSTALL_DIR}/app/Protege.ico
Terminal=false
Type=Application
Categories=Development;Education;
EOF
chmod +x "$HOME/.local/share/applications/protege.desktop"

echo
echo "Готово! Запуск: меню → Protégé, или в терминале: ~/protege/run.sh"
