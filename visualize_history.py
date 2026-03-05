import sqlite3
import json
import logging
import os
import hashlib
import time
from datetime import datetime
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import settings
from db_manager import HistoryDB

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NKON History - {product_name}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container {
            max-width: 1200px;
            width: 100%;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        h1 {
            color: #3b82f6;
            font-size: 1.5rem;
            margin-bottom: 5px;
        }
        .product-link {
            color: #60a5fa;
            text-decoration: none;
            word-break: break-all;
        }
        .product-link:hover { text-decoration: underline; }
        
        .card {
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: rgba(15, 23, 42, 0.5);
            border-radius: 12px;
            padding: 15px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .stat-value {
            font-size: 1.8rem;
            font-weight: 800;
            color: #f8fafc;
        }
        .stat-label {
            font-size: 0.85rem;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 5px;
        }
        .chart-container {
            position: relative;
            height: 350px;
            width: 100%;
        }
        @media (max-width: 768px) {
            .chart-container { height: 250px; }
            h1 { font-size: 1.2rem; }
            .stat-value { font-size: 1.4rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><a href="{product_url}" target="_blank" class="product-link">{product_name}</a></h1>
            <p style="color:#94a3b8; font-size:0.9rem;">Оновлено: {last_updated}</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value" id="current-price">€ --</div>
                <div class="stat-label">Ціна</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="current-stock" style="color: #10b981;">--</div>
                <div class="stat-label">В наявності</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="current-preorder" style="color: #f59e0b;">--</div>
                <div class="stat-label">У дорозі</div>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-top:0; color:#cbd5e1; font-weight:600;">Наявність (шт)</h3>
            <div class="chart-container">
                <canvas id="stockChart"></canvas>
            </div>
        </div>

        <div class="card">
            <h3 style="margin-top:0; color:#cbd5e1; font-weight:600;">Історія Ціни (€)</h3>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>
    </div>

    <script>
        const dashboardData = {__DATA__};
        
        // Update stats
        if(dashboardData.price_history.length > 0) {
            const lastPrice = dashboardData.price_history[dashboardData.price_history.length-1].y;
            document.getElementById('current-price').innerText = '€' + lastPrice.toFixed(2);
        }
        if(dashboardData.stock_history.length > 0) {
            const lastStock = dashboardData.stock_history[dashboardData.stock_history.length-1];
            document.getElementById('current-stock').innerText = lastStock.in_stock;
            document.getElementById('current-preorder').innerText = lastStock.preorder;
        }

        // Common Chart Defaults
        Chart.defaults.color = '#94a3b8';
        Chart.defaults.font.family = "'Inter', sans-serif";

        // Stock Chart (Stacked Area)
        const ctxStock = document.getElementById('stockChart').getContext('2d');
        new Chart(ctxStock, {
            type: 'line',
            data: {
                datasets: [
                    {
                        label: 'В наявності',
                        data: dashboardData.stock_history.map(d => ({x: d.x, y: d.in_stock})),
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.2)',
                        fill: true,
                        stepped: true,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 5
                    },
                    {
                        label: 'Передзамовлення',
                        data: dashboardData.stock_history.map(d => ({x: d.x, y: d.preorder})),
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245, 158, 11, 0.2)',
                        fill: true,
                        stepped: true,
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 5
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'dd.MM.yyyy HH:mm' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    }
                },
                plugins: {
                    legend: { position: 'top' },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        titleColor: '#f8fafc',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1
                    }
                }
            }
        });

        // Price Chart (Stepped Line)
        const ctxPrice = document.getElementById('priceChart').getContext('2d');
        new Chart(ctxPrice, {
            type: 'line',
            data: {
                datasets: [{
                    label: 'Ціна (€)',
                    data: dashboardData.price_history,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    stepped: true,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 5
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'nearest',
                    intersect: false,
                    axis: 'x'
                },
                scales: {
                    x: {
                        type: 'time',
                        time: { tooltipFormat: 'dd.MM.yyyy HH:mm' },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        beginAtZero: false,
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: {
                            callback: function(value) { return '€' + value; }
                        }
                    }
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        titleColor: '#f8fafc',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                return ' Ціна: €' + context.parsed.y.toFixed(2);
                            }
                        }
                    }
                }
            }
        });
    </script>
</body>
</html>
"""

class HistoryVisualizer:
    def __init__(self, db_path="nkon_history.db"):
        self.db_path = db_path
        self.ftp_host = settings.FTP_HOST
        self.ftp_user = settings.FTP_USER
        self.ftp_pass = settings.FTP_PASS
        self.ftp_dir = settings.FTP_DIR
        self.output_dir = "html_output"
        os.makedirs(self.output_dir, exist_ok=True)

    def _inject_statcounter(self, html_content: str) -> str:
        """
        Вбудовує код Statcounter в HTML.
        Якщо налаштування (STATCOUNTER_PROJECT та STATCOUNTER_SECURITY) не задані,
        повертає оригінальний HTML.
        Для уникнення поломок з різними версіями HTML_TEMPLATE (напр. з GitHub)
        код просто вставляється перед тегом </body>.
        """
        if not settings.STATCOUNTER_PROJECT or not settings.STATCOUNTER_SECURITY:
            return html_content

        statcounter_snippet = f"""
<!-- Default Statcounter code for NKON Informer Graphs -->
<script type="text/javascript">
var sc_project={settings.STATCOUNTER_PROJECT}; 
var sc_invisible=1; 
var sc_security="{settings.STATCOUNTER_SECURITY}"; 
</script>
<script type="text/javascript"
src="https://www.statcounter.com/counter/counter.js" async></script>
<noscript><div class="statcounter"><a title="Web Analytics"
href="https://statcounter.com/" target="_blank"><img class="statcounter"
src="https://c.statcounter.com/{settings.STATCOUNTER_PROJECT}/0/{settings.STATCOUNTER_SECURITY}/1/"
alt="Web Analytics" referrerPolicy="no-referrer-when-downgrade"></a></div></noscript>
<!-- End of Statcounter Code -->
</body>"""

        # Замінюємо закриваючий тег </body> на наш сніпет + </body>
        # Використовуємо .replace() з обмеженням в 1 заміну для безпеки
        if "</body>" in html_content:
            return html_content.replace("</body>", statcounter_snippet, 1)
        return html_content

    def extract_data(self, product_ids=None):
        """Витягує дані з бази та форматує для Chart.js. Якщо product_ids задано, бере тільки їх."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get products
        if product_ids:
            placeholders = ','.join(['?'] * len(product_ids))
            cursor.execute(f"SELECT id, product_key, name, url FROM products WHERE id IN ({placeholders})", product_ids)
        else:
            cursor.execute("SELECT id, product_key, name, url FROM products")
        
        products = cursor.fetchall()

        results = {}
        for p in products:
            p_id = p['id']
            p_key = p['product_key']
            graph_id = hashlib.md5(p_key.encode()).hexdigest()[:8]
            
            # Get Price History
            cursor.execute("SELECT timestamp, price FROM price_history WHERE product_id = ? ORDER BY timestamp ASC", (p_id,))
            price_history = []
            for row in cursor.fetchall():
                # Chart.js time adapter expects ISO or valid JS dates
                ts = row['timestamp'].replace(' ', 'T')
                price_history.append({"x": ts, "y": row['price']})

            # Get Stock History
            cursor.execute("SELECT timestamp, in_stock_qty, preorder_qty FROM stock_history WHERE product_id = ? ORDER BY timestamp ASC", (p_id,))
            stock_history = []
            for row in cursor.fetchall():
                ts = row['timestamp'].replace(' ', 'T')
                stock_history.append({
                    "x": ts, 
                    "in_stock": row['in_stock_qty'] or 0, 
                    "preorder": row['preorder_qty'] or 0
                })
                
            # Extend final points to NOW to draw the graph until current time
            if price_history:
                now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                price_history.append({"x": now_str, "y": price_history[-1]['y']})
            if stock_history:
                now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                last_stock = stock_history[-1].copy()
                last_stock['x'] = now_str
                stock_history.append(last_stock)

            results[p_id] = {
                "id": p_id,
                "graph_id": graph_id,
                "name": p['name'],
                "url": p['url'],
                "price_history": price_history,
                "stock_history": stock_history
            }

        conn.close()
        return results

    def generate_htmls(self, product_ids=None):
        """Генерує локальні HTML файли. Якщо product_ids задано, бере тільки їх."""
        data = self.extract_data(product_ids=product_ids)
        generated_files = []
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        for p_id, p_data in data.items():
            if not p_data['price_history'] and not p_data['stock_history']:
                continue # Skip if completely empty

            json_data = json.dumps({
                "price_history": p_data['price_history'],
                "stock_history": p_data['stock_history']
            })

            html_content = HTML_TEMPLATE.replace(
                "{product_name}", p_data['name']
            ).replace(
                "{product_url}", p_data['url']
            ).replace(
                "{last_updated}", now_str
            ).replace(
                "{__DATA__}", json_data
            )

            # --- Ін'єкція аналітики ---
            # Виконується динамічно, щоб не залежати від жорсткого HTML_TEMPLATE
            html_content = self._inject_statcounter(html_content)

            graph_id = p_data['graph_id']
            file_path = os.path.join(self.output_dir, f"graph_{graph_id}.html")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            generated_files.append((file_path, f"graph_{graph_id}.html"))
            
        return generated_files

    def capture_screenshots(self, driver, files):
        """
        Captures screenshots of generated HTML files using the provided Selenium driver.
        Returns a list of paths to the generated PNG files.
        """
        png_files = []
        if not files:
            return png_files

        logger.info(f"Зняття скріншотів для {len(files)} графіків...")
        
        try:
            for html_path, _ in files:
                abs_html_path = os.path.abspath(html_path)
                file_url = f"file:///{abs_html_path.replace('\\', '/')}"
                
                logger.info(f"Loading {file_url}...")
                driver.get(file_url)
                
                # Wait for Chart.js animations to finish (approx 1-2s)
                time.sleep(2)
                
                # Try to find the container
                try:
                    container = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "container"))
                    )
                    
                    png_path = html_path.replace(".html", ".png")
                    container.screenshot(png_path)
                    
                    png_files.append(png_path)
                    logger.info(f"✅ Screenshot saved: {png_path}")
                except Exception as e:
                    logger.error(f"Error capturing screenshot for {html_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Critical error in capture_screenshots: {e}")
            
        return png_files

    def upload_to_sftp(self, files):
        """Завантажує згенеровані файли на SFTP сервер"""
        if not files:
            logger.info("Немає файлів для вивантаження.")
            return

        logger.info(f"Підключення до SFTP {self.ftp_host}...")
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=self.ftp_host, username=self.ftp_user, password=self.ftp_pass, timeout=15)
            
            sftp = client.open_sftp()
            
            if self.ftp_dir and self.ftp_dir != '/':
                try:
                    sftp.chdir(self.ftp_dir)
                except Exception as e:
                    logger.warning(f"Could not change to FTP_DIR {self.ftp_dir}: {e}")
            
            for local_path, remote_name in files:
                logger.info(f"Uploading {remote_name}...")
                sftp.put(local_path, remote_name)
                
            sftp.close()
            client.close()
            logger.info(f"✅ Успішно завантажено {len(files)} графіків на сервер!")
            
            # Очищення локальних тимчасових файлів після успішного завантаження
            for local_path, _ in files:
                try:
                    if local_path.endswith('.html'):
                        os.remove(local_path)
                except Exception as e:
                    logger.warning(f"Не вдалося видалити тимчасовий файл {local_path}: {e}")
            logger.info("🧹 Локальні тимчасові файли очищено.")

        except Exception as e:
            logger.error(f"❌ Помилка SFTP: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Генератор графіків історії для NKON Monitor")
    parser.add_argument("--local-only", action="store_true", help="Згенерувати HTML тільки локально, без завантаження на FTP")
    args = parser.parse_args()

    visualizer = HistoryVisualizer()
    files = visualizer.generate_htmls()
    logger.info(f"Згенеровано {len(files)} HTML файлів.")
    
    if args.local_only:
        logger.info("Режим --local-only: Файли залишені в директорії html_output/. Вивантаження на FTP пропущено.")
    else:
        visualizer.upload_to_sftp(files)
