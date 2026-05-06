"""
data_collector/plasway_crawler.py
─────────────────────────────────
专门用于遍历抓取 www.plasway.com/datasheet 的全站爬虫。
由于未知其具体的 DOM 结构和分页机制，本爬虫采用了一种泛用性的链接发现机制：
1. 访问首页，收集所有看起来像物性表详情页的链接。
2. 收集分页链接（如包含 page= 的链接）并继续抓取下一页。
3. 对每个详情页提取纯文本，复用已有的正则引擎提取工艺参数。
"""

import sys
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# 引入现有 scraper 模块中的存储与正则提取逻辑
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from data_collector.scraper import extract_params_regex, _empty_grade, _save, HEADERS

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("plasway_crawler")

BASE_URL = "https://www.plasway.com"
START_URL = "https://www.plasway.com/datasheet"

def is_valid_detail_link(href: str) -> bool:
    """严格判断链接是否为物性表详情页"""
    return bool(href and "/datasheet/detail/" in href)

def crawl_all(max_pages=50):
    """遍历所有分页并抓取所有牌号数据"""
    all_detail_links = set()

    log.info("=== 阶段 1: 发现所有牌号详情链接 ===")
    
    for page_num in range(1, max_pages + 1):
        current_url = f"https://www.plasway.com/datasheet?page={page_num}"
        log.info(f"正在扫描列表页: {current_url}")
        
        try:
            r = requests.get(current_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                log.warning(f"页面 {current_url} 返回状态码 {r.status_code}，停止翻页。")
                break
                
            soup = BeautifulSoup(r.text, "html.parser")
            
            new_links_count = 0
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                full_url = urljoin(BASE_URL, href)
                
                if is_valid_detail_link(full_url) and full_url not in all_detail_links:
                    all_detail_links.add(full_url)
                    new_links_count += 1
                    
            if new_links_count == 0:
                log.info(f"第 {page_num} 页没有新的物性表链接，判定已达末页，结束扫描。")
                break
                
            time.sleep(1.0)  # 礼貌性延时
            
        except Exception as e:
            log.warning(f"访问列表页失败 {current_url}: {e}")
            break

    log.info(f"=== 阶段 1 结束: 共发现 {len(all_detail_links)} 个可能的物性表链接 ===")
    
    if not all_detail_links:
        log.warning("未找到任何详情页链接，可能是网站结构与启发式规则不匹配。")
        return

    log.info("=== 阶段 2: 抓取详情数据并提取参数 ===")
    success_count = 0
    
    for i, link in enumerate(all_detail_links, 1):
        log.info(f"[{i}/{len(all_detail_links)}] 抓取: {link}")
        try:
            r = requests.get(link, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
                
            soup = BeautifulSoup(r.text, "html.parser")
            
            # 提取牌号名称 (通常在 h1 或 title)
            h1 = soup.find("h1")
            if h1:
                grade_name = h1.get_text(strip=True)
            else:
                title = soup.find("title")
                grade_name = title.get_text(strip=True).split("-")[0].strip() if title else "Unknown_Grade"
                
            if not grade_name or grade_name == "Unknown_Grade":
                continue

            # 提取所有纯文本供正则匹配 (保留基础的正则提取以兼容老数据结构)
            page_text = soup.get_text(" ", strip=True)
            params = extract_params_regex(page_text)

            # 动态提取表格属性 (根据用户提供的页面结构)
            dynamic_props = {}
            current_category = "General"
            last_prop_name = ""
            
            for tr in soup.find_all("tr"):
                # 获取该行的所有单元格
                cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
                if not cells:
                    continue
                
                # 跳过表头行
                if len(cells) == 5 and "测试结果" in cells:
                    continue
                
                # 识别分类头 (通常只有一个单元格，或者带有特定样式)
                if len(cells) == 1:
                    current_category = cells[0]
                    continue
                    
                # 处理属性行: 物性性能 | 测试条件 | 测试方法 | 测试结果 | 测试单位
                if len(cells) >= 4:
                    if len(cells) == 5:
                        prop_name, cond, method, res, unit = cells
                        if prop_name and prop_name != "-":
                            last_prop_name = prop_name
                        else:
                            prop_name = last_prop_name
                        if cond and cond != "-":
                            prop_name = f"{prop_name} ({cond})"
                    elif len(cells) == 4:
                        # 发生了 rowspan 导致第一个单元格缺失
                        cond, method, res, unit = cells
                        prop_name = f"{last_prop_name} ({cond})" if cond and cond != "-" else last_prop_name
                    else:
                        prop_name = cells[0]
                        res = cells[-2]
                        unit = cells[-1]
                        
                    if res and res != "-":
                        key = prop_name.strip()
                        if unit and unit != "-":
                            key += f" [{unit}]"
                        if current_category not in dynamic_props:
                            dynamic_props[current_category] = {}
                        dynamic_props[current_category][key] = res

            # 判断页面有效性: 只要提取到了表格属性或者正则提取到了加工参数即可
            if not dynamic_props and not params["processing"] and not params["mechanical"] and not params["thermal"]:
                log.info(f"  -> 未能从页面中提取到有效物理/加工参数，跳过。")
                continue

            # 构建并保存数据格式
            data = _empty_grade(grade_name, [link], "plasway_bulk")
            data["grade_name"] = grade_name
            # 将正则提取的基础参数依然放入标准结构中
            for sec in ("processing", "thermal", "mechanical"):
                data[sec].update(params.get(sec, {}))
            
            # 存入动态提取的完整全量属性
            data["dynamic_properties"] = dynamic_props
            
            data["raw_text"] = page_text[:4000]

            _save(data)
            success_count += 1
            
            time.sleep(1.5)  # 礼貌性延时，避免被封禁
            
        except Exception as e:
            log.error(f"  -> 处理页面失败 {link}: {e}")

    log.info(f"=== 抓取任务完成: 共成功获取并保存 {success_count} 个牌号的参数。===")

if __name__ == "__main__":
    print("开始执行 Plasway 全站批量爬虫...")
    crawl_all()
