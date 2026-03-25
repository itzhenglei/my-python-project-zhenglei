"""
邮件内 8×10 号码矩阵：先生成结构化 grid，再转为带 CSS 类的 HTML 片段。

说明：快乐 8 号码 1–80 按行优先填满表格；单元格根据开奖/推荐/命中叠样式。
"""
from typing import Dict, List


def generate_period_grid(period_data: Dict) -> List[List[Dict]]:
    """
    构建 8 行 × 10 列，每格包含 number 与展示所需布尔/标签。

    type_labels：该股同时属于哪些推荐源简称（开/试/金/关/对），用于角标与多荐样式。
    """
    grid = []

    lottery_numbers = set(period_data.get('lottery_numbers', []))
    kaiji = set(period_data.get('kaiji', []))
    shiji = set(period_data.get('shiji', []))
    jin = set(period_data.get('jin', []))
    guanzhu = set(period_data.get('guanzhu', []))
    duiying = set(period_data.get('duiying', []))

    for row in range(8):
        grid_row = []
        for col in range(10):
            num = row * 10 + col + 1

            is_lottery = num in lottery_numbers
            is_kaiji = num in kaiji
            is_shiji = num in shiji
            is_jin = num in jin
            is_guanzhu = num in guanzhu
            is_duiying = num in duiying

            is_recommend = is_kaiji or is_shiji or is_jin or is_guanzhu or is_duiying
            is_hit = is_lottery and is_recommend

            type_labels = []
            if is_kaiji:
                type_labels.append('开')
            if is_shiji:
                type_labels.append('试')
            if is_jin:
                type_labels.append('金')
            if is_guanzhu:
                type_labels.append('关')
            if is_duiying:
                type_labels.append('对')

            grid_row.append({
                'number': num,
                'is_lottery': is_lottery,
                'is_recommend': is_recommend,
                'is_hit': is_hit,
                'type_labels': type_labels
            })

        grid.append(grid_row)

    return grid


def generate_grid_html(grid: List[List[Dict]], has_lottery: bool = True) -> str:
    """
    将 grid 转为 div 网格 HTML。has_lottery=False 时仍可标推荐但不标「纯开奖」色，避免误读。

    CSS 类优先级：hit > lottery > multi/double recommend > single recommend。
    """
    grid_html = ""
    
    for row_idx, row in enumerate(grid):
        grid_html += f'<div class="grid-row">\n'
        for cell in row:
            num = cell['number']
            
            class_name = "grid-cell"
            
            if cell['is_hit']:
                class_name += " hit"
            elif cell['is_lottery'] and has_lottery:
                class_name += " lottery"
            elif cell['is_recommend']:
                if len(cell['type_labels']) >= 3:
                    class_name += " multi-recommend"
                elif len(cell['type_labels']) >= 2:
                    class_name += " double-recommend"
                else:
                    class_name += " recommend"
            
            data_attrs = ""
            if cell['type_labels']:
                data_attrs = f' data-types="{",".join(cell["type_labels"])}"'
            
            grid_html += f'<div class="{class_name}"{data_attrs}>{num:02d}</div>\n'
        
        grid_html += '</div>\n'
    
    return grid_html
