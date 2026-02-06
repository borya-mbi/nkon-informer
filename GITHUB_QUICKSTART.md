# 🚀 Швидкий старт - Публікація на GitHub

> [!IMPORTANT]
> **Git має бути встановлений!** Якщо Git ще не встановлено, дивіться → [GIT_INSTALL_WINDOWS.md](GIT_INSTALL_WINDOWS.md)

## Крок 1: Створіть репозиторій на GitHub

1. Відкрийте https://github.com/new
2. Repository name: `nkon-informer`
3. Public ✓
4. **НЕ** додавайте README/gitignore
5. Create repository

## Крок 2: Команди у PowerShell

```powershell
# Перейдіть у папку проєкту
cd H:\Work\MBI\Education\AG\nkon-informer

# Ініціалізація (якщо ще не зроблено)
git init

# Додайте всі файли
git add .

# Перший commit
git commit -m "Initial commit: NKON LiFePO4 Monitor"

# Підключіть GitHub
git remote add origin https://github.com/borya-mbi/nkon-informer.git

# Створіть main гілку
git branch -M main

# Відправте на GitHub
git push -u origin main
```

## Після публікації:

URL вашого проєкту: `https://github.com/borya-mbi/nkon-informer`

Клонування: `git clone https://github.com/borya-mbi/nkon-informer.git`

## Наступні оновлення:

```powershell
git add .
git commit -m "Опис змін"
git push
```

---

**Детальна інструкція:** GITHUB_SETUP.md
