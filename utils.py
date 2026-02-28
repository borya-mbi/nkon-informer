#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility functions for NKON Monitor
"""

import re

def clean_price(price_text: str) -> float:
    """
    Очищення та конвертація ціни в float
    
    Args:
        price_text: Текст ціни (наприклад, "€ 89.95" або "€89.95")
        
    Returns:
        Ціна як float або None
    """
    if not price_text:
        return None
        
    # Видалення символу євро та інших нецифрових символів, крім крапки
    cleaned = re.sub(r'[^\d.]', '', price_text.replace(',', '.'))
    
    try:
        return float(cleaned)
    except ValueError:
        return None

def extract_capacity(text: str) -> int:
    """
    Витягування ємності батареї з тексту
    
    Args:
        text: Текст для пошуку
        
    Returns:
        Ємність в Ah або None
    """
    if not text:
        return None
        
    # Пошук чисел перед Ah, Ah, AH, aH
    match = re.search(r'(\d{3,})\s*(?:Ah|ah|AH|aH)', text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None

def extract_grade(text: str) -> str:
    """
    Витягування грейду (Grade A/B) з назви
    Підтримує англійську (Grade) та українську (Клас) версії
    """
    # Grade A, Grade A-, Клас A, Група A, B-Grade тощо
    match = re.search(r'(?i)(?:(?:Grade|Клас|Група)\s*[A-BА-Б][-+]?|[A-BА-Б]-Grade)', text)
    if match:
        grade = match.group(0)
        # Нормалізація: B-Grade -> Grade B
        if len(grade) > 1 and grade[1] == '-': 
            return f"Grade {grade[0]}"
        # Клас A -> Grade A, Група A -> Grade A
        grade = re.sub(r'(?i)(Клас|Група)', 'Grade', grade)
        # Нормалізація літер (Кирилиця А/Б -> Латиниця A/B)
        grade = grade.replace('А', 'A').replace('Б', 'B')
        grade = grade.title()  # grade a -> Grade A
        return grade
    return "?"

def shorten_name(text: str) -> str:
    """
    Скорочення назви товару для компактності
    Підтримує англійську та українську версії
    """
    # 1. Видаляємо грейд (бо ми його показуємо окремо)
    # Підтримка Grade/Клас/Група
    text = re.sub(r'(?i)(?:(?:Grade|Клас|Група)\s*[A-BА-Б][-+]?|[A-BА-Б]-Grade)', '', text)
    
    # 2. Видаляємо технічні характеристики (бо вони зрозумілі з контексту)
    remove_words = [
        r'LiFePO4', r'3\.2V', r'Prismatic', r'Rechargeable', 
        r'Battery', r'Cell', r'\d+\s*Ah',  # Ємність вже є на початку
        r'Призматичний'  # Українська "Prismatic"
    ]
    
    for word in remove_words:
        text = re.sub(f'(?i){word}', '', text)
        
    # 3. Видаляємо зайві символи та пробіли
    text = text.replace(' - ', ' ').replace(' , ', ' ')
    
    # Видаляємо дублікати пробілів
    text = ' '.join(text.split())
    
    # Видаляємо зайві символи в кінці та на початку (тире, коми, крапки)
    text = text.strip(" -.,|")
    
    # Максимальна довжина (обрізаємо якщо задовга)
    if len(text) > 30:
        text = text[:28] + ".."
        
    return text.strip()

def mask_sensitive(text: str) -> str:
    """Маскування чутливих даних в логах"""
    if not text: return ""
    text_str = str(text)
    if len(text_str) <= 12:
        return "***"
    return f"{text_str[:4]}***{text_str[-4:]}"
