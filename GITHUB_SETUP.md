# 🚀 Публікація проєкту на GitHub

Інструкція з публікації NKON Monitor на GitHub для зручного встановлення та оновлення.

## 📋 Що ви отримаєте:

- ✅ Простий URL для клонування: `git clone https://github.com/borya-mbi/nkon-informer.git`
- ✅ Легкі оновлення: просто `git pull`
- ✅ Історія змін
- ✅ Можливість повернутися до попередньої версії
- ✅ Зручний перегляд коду онлайн

---

## 🎯 Крок 1: Створення репозиторію на GitHub

### Через Web браузер:

1. **Відкрийте GitHub:**
   - Перейдіть на https://github.com
   - Увійдіть в акаунт `borya-mbi`

2. **Створіть новий репозиторій:**
   - Натисніть **"+"** вгорі справа → **"New repository"**
   
   **Налаштування:**
   - Repository name: `nkon-informer`
   - Description: `LiFePO4 Battery Monitor for NKON.nl with Telegram notifications`
   - Visibility: 
     - ☑ **Public** (рекомендовано - безкоштовно, можнаділитися)
     - ⬜ Private (якщо не хочете щоб хтось бачив код)
   - ⬜ **НЕ** додавайте README, .gitignore, license

3. **Натисніть "Create repository"**

---

## 🔧 Крок 2: Ініціалізація Git локально

Відкрийте PowerShell у папці проєкту:

```powershell
cd H:\Work\MBI\Education\AG\nkon-informer

# Ініціалізація Git репозиторію (якщо ще не ініціалізовано)
git init

# Перевірте статус
git status
```

---

## 📤 Крок 3: Додавання файлів до Git

```powershell
# Додайте всі файли (.env автоматично ігнорується завдяки .gitignore)
git add .

# Перевірте що буде додано (.env НЕ має бути в списку!)
git status

# Створіть перший commit
git commit -m "Initial commit: NKON LiFePO4 Monitor"
```

---

## 🌐 Крок 4: Підключення до GitHub

```powershell
# Додайте віддалений репозиторій
git remote add origin https://github.com/borya-mbi/nkon-informer.git

# Перевірте
git remote -v
```

---

## 🚀 Крок 5: Публікація на GitHub

```powershell
# Створіть основну гілку (main)
git branch -M main

# Відправте код на GitHub
git push -u origin main
```

**Якщо попросить аутентифікацію:**
- Username: `borya-mbi`
- Password: використайте **Personal Access Token** (не звичайний пароль!)

---

## 🔑 Створення Personal Access Token (якщо потрібно)

1. GitHub → Settings (ваш профіль) → Developer settings
2. Personal access tokens → Tokens (classic) → Generate new token
3. Налаштування:
   - Note: `nkon-informer-upload`
   - Expiration: `90 days` (або більше)
   - Scopes: ☑ `repo` (Full control of private repositories)
4. **Generate token** → **СКОПІЮЙТЕ** токен (показується тільки раз!)
5. Використовуйте цей токен замість паролю при `git push`

---

## ✅ Крок 6: Перевірка

1. Відкрийте https://github.com/borya-mbi/nkon-informer
2. Ви маєте побачити всі файли проєкту
3. **ВАЖЛИВО:** Перевірте що `.env` **НЕ** опублікований (містить токени!)

---

## 🔄 Крок 7: Оновлення документації з URL

Після публікації оновіть `PROXMOX_DEPLOYMENT.md`:

**Замість:**
```bash
git clone https://github.com/borya-mbi/nkon-informer.git nkon-informer
```

**Напишіть:**
```bash
git clone https://github.com/borya-mbi/nkon-informer.git nkon-informer
```

> [!NOTE]
> URL вже правильний! Цей розділ для довідки.

---

## 📝 Робота з репозиторієм (на майбутнє)

### Додавання змін:

```powershell
cd H:\Work\MBI\Education\AG\nkon-informer

# Перевірте зміни
git status

# Додайте змінені файли
git add nkon_monitor.py README.md

# Або всі зміни:
git add .

# Commit з описом
git commit -m "Опис змін, наприклад: Додано підтримку множинних чатів"

# Відправте на GitHub
git push
```

### Перегляд історії:

```powershell
# Історія commits
git log --oneline

# Детальна історія останніх 5 commits
git log -5
```

### Відкат змін:

```powershell
# Скасувати незбережені зміни
git checkout -- nkon_monitor.py

# Повернутися до попереднього commit (обережно!)
git reset --hard HEAD~1
```

---

## 🌟 Додаткові налаштування (опціонально)

### Додати README badge:

Додайте до `README.md` у самий верх:

```markdown
# 🔋 NKON LiFePO4 Monitor

[![GitHub](https://img.shields.io/badge/GitHub-borya--mbi%2Fnkon--informer-blue?logo=github)](https://github.com/borya-mbi/nkon-informer)
[![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
```

### Створити LICENSE:

```powershell
# Створіть файл LICENSE
@"
MIT License

Copyright (c) 2026 borya-mbi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"@ | Out-File -FilePath LICENSE -Encoding UTF8

git add LICENSE
git commit -m "Add MIT License"
git push
```

---

## 🎓 Корисні Git команди

```powershell
# Статус репозиторію
git status

# Різниця (що змінилося)
git diff

# Історія
git log --oneline --graph --all

# Скасувати git add (до commit)
git reset HEAD file.py

# Відтягнути зміни з GitHub
git pull

# Клонувати репозиторій
git clone https://github.com/borya-mbi/nkon-informer.git
```

---

## ⚠️ Важливі нагадування:

1. **НІКОЛИ не комітьте `.env`** (містить токени!)
2. Перевіряйте `git status` перед `git add`
3. Пишіть зрозумілі commit messages
4. Регулярно робіть `git push` для резервного копіювання

---

## 🆘 Troubleshooting

### Помилка: "remote origin already exists"
```powershell
git remote remove origin
git remote add origin https://github.com/borya-mbi/nkon-informer.git
```

### Помилка: "Authentication failed"
- Використовуйте Personal Access Token замість паролю
- Або налаштуйте SSH ключі

### Випадково додали .env
```powershell
# Видалити з Git (але залишити локально)
git rm --cached .env
git commit -m "Remove .env from tracking"
git push
```

---

**Готово! Тепер ваш проєкт на GitHub! 🎉**

URL: `https://github.com/borya-mbi/nkon-informer`
