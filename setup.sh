#!/usr/bin/env bash
# Установка и первоначальная настройка study: код, токены, каталоги, проверка связи.
#
# Из каталога с инструментом:  bash setup.sh
# Отдельно, одной командой:    см. раздел «Установка» в README.
set -euo pipefail

REPO=${STUDY_REPO:-https://github.com/nowherewashere/study-digest.git}
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '  ! %s\n' "$1"; }
ok() { printf '  + %s\n' "$1"; }

# Тильда в пути, введённом руками или заданном настройкой.
untilde() {
  case $1 in "~/"*) printf '%s' "$HOME/${1#\~/}" ;; *) printf '%s' "$1" ;; esac
}

# Значение настройки: переменная окружения → строка в config.env → значение по умолчанию.
cfg() {
  local key=$1 default=${2:-} value=${!1:-}
  if [ -z "$value" ] && [ -f "$CONFIG" ]; then
    value=$(sed -n "s/^$key=//p" "$CONFIG" | tail -1 | tr -d '[:space:]')
  fi
  printf '%s' "${value:-$default}"
}

# Путь из настройки: относительный отсчитывается от корня учебной директории.
expand() {
  local path
  path=$(untilde "$1")
  case $path in /*) printf '%s' "$path" ;; *) printf '%s' "$ROOT/$path" ;; esac
}

# --- 1. Зависимости

bold "Зависимости"
command -v git >/dev/null || { warn "git не найден"; exit 1; }
ok "git $(git --version | awk '{print $3}')"

command -v python3 >/dev/null || { warn "python3 не найден"; exit 1; }
python3 - <<'PYVER' || { warn "нужен python3 3.8 или новее"; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 8) else 1)
PYVER
ok "python3 $(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

# --- 2. Код

bold $'\nКод'
if [ -x "$HERE/study" ]; then
  DIGEST=$HERE
  ok "уже на месте: $DIGEST"
else
  # Скрипт скачали отдельно — сначала забираем сам инструмент.
  default=$HOME/study/digest
  target=""
  if [ -t 0 ]; then
    read -r -p "  куда установить [$default]: " target
  fi
  target=$(untilde "${target:-$default}")
  if [ -x "$target/study" ]; then
    ok "уже установлено: $target"
  elif [ -d "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ]; then
    warn "$target существует и не пуст"
    exit 1
  else
    git clone --quiet "$REPO" "$target"
    ok "склонировано в $target"
  fi
  DIGEST=$target
fi
ROOT=$(dirname "$DIGEST")
CONFIG=$DIGEST/config.env
if [ ! -f "$CONFIG" ]; then
  cp "$DIGEST/config.env.example" "$CONFIG"
  ok "создан config.env из примера — курсы вписать после установки"
fi
ok "корень учебной директории: $ROOT"

# --- 3. Токены

ask_token() {
  local key=$1 name=$2 where=$3 path token answer
  path=$(expand "$(cfg "$key")")
  printf '\n%s\n' "$name"
  printf '  файл: %s\n' "$path"
  printf '  где взять: %s\n' "$where"

  if [ -s "$path" ]; then
    read -r -p "  токен уже есть, заменить? [y/N] " answer
    case ${answer:-n} in [yY]*) ;; *) ok "оставлен прежний"; return 0 ;; esac
  fi

  read -r -s -p "  вставь токен (ввод не отображается, Enter — пропустить): " token
  printf '\n'
  if [ -z "$token" ]; then
    warn "пропущено, команды этого сервиса работать не будут"
    return 0
  fi

  mkdir -p "$(dirname "$path")"
  chmod 700 "$(dirname "$path")"
  (umask 077; printf '%s' "$token" > "$path")
  chmod 600 "$path"
  ok "сохранён, права $(stat -c '%a' "$path")"
}

bold $'\nТокены'
if [ ! -t 0 ]; then
  warn "нет терминала, ввод токенов пропущен"
else
  ask_token TUIS_TOKEN_FILE "Moodle" \
    "профиль → «Ключи безопасности» → служба Moodle mobile web service"
  ask_token GITVERSE_TOKEN_FILE "GitVerse" \
    "иконка пользователя → Настройки → Управление токенами, доступ «Репозитории»"
  ask_token SOURCECRAFT_TOKEN_FILE "SourceCraft" \
    "Home → Access → Personal Access Tokens"
fi

# --- 4. Каталоги

bold $'\nКаталоги'
state=$(expand "$(cfg DIGEST_STATE "~/.config/tuis/state.json")")
mkdir -p "$(dirname "$state")"
ok "$(dirname "$state") — снимок состояния сводки"

courses=0
while read -r _ _ code title; do
  case ${code:-} in ""|"-") continue ;; esac
  mkdir -p "$ROOT/$code/stash" "$ROOT/$code/tuis"
  ok "$ROOT/$code/{stash,tuis} — $title"
  courses=$((courses + 1))
done < <(grep -E '^COURSE[[:space:]]+[0-9]+' "$CONFIG" 2>/dev/null || true)
[ "$courses" -gt 0 ] || warn "в config.env нет строк COURSE с кодом каталога"

# --- 5. Проверка

bold $'\nПроверка'
if "$DIGEST/study" me 2>/dev/null; then
  ok "токен Moodle работает"
else
  warn "Moodle не отвечает — проверь токен и TUIS_URL в config.env"
fi

bold $'\nДальше'
cat <<NEXT
  $DIGEST/study courses     готовые строки COURSE для config.env
  $DIGEST/study digest      первый запуск сохраняет снимок состояния
  $DIGEST/study files <код предмета> --pull    забрать материалы курса в stash/

Ежедневная сводка: Claude Code Desktop → Code → Routines → New routine → Local,
рабочая папка $ROOT, в Instructions — текст из $DIGEST/daily-digest-prompt.md.
NEXT
