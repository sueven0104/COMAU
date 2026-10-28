"""LLM 结构化抽取：任意格式内容 → 统一 quote_items 记录（含重试）。"""
import json
from .llm_client import LLMError
from .normalize import validate_item

SYSTEM_EXTRACT = """你是采购报价数据抽取助手，从汽车焊装线设备询价/报价内容中抽取每一条报价明细。
只输出 JSON，不要任何解释。格式：
{"items":[
  {"supplier":"供应商","category":"品类","product_name":"设备名称","spec":"规格/配置描述",
   "brand":"品牌","model":"型号","qty":数字或null,"unit":"台/套/m/条等",
   "unit_price":数字或null,"currency":"CNY/USD/EUR等，拿不准填null","tax_included":true/false/null,
   "price_status":"成交价/本次报价/历史报价/预估价/未标注","quote_date":"YYYY-MM-DD或null",
   "terms":"付款/交付等商务条款","source_location":"来源位置，如 Sheet名!R行号 或 第N页"}],
 "email_terms":"邮件正文中的商务条款汇总，无则null",
 "supplier_name":"本文件/邮件所属供应商，判断不出则null"}
规则：
1. 价格一律转纯数字（去掉货币符号、千分位）；百分比、编号不是价格。
2. 汇总行/合计行/设计费管理费等非设备行也要抽取（product_name 写明"机械设计费"等），便于总价核对。
3. 拿不准的字段填 null，禁止编造；币种按文件注明的货币（人民币/美元/欧元）填写，未注明则填 null。
4. 品类从"已知品类"列表中选最接近的；supplier 优先从"已知供应商"列表选最接近的，都不符合才自拟。
5. 同一文件多 Sheet/多页都要覆盖，不要遗漏。
6. 若内容是图片（截图/PDF扫描页），逐张图片中的表格逐行抽取，不要遗漏；source_location 写"第N张图"。"""

def extract_from_payload(client, file_label, payload_text, images=None,
                         known_categories=(), known_suppliers=()):
    hint = (f"已知品类：{','.join(known_categories) or '无'}\n"
            f"已知供应商：{','.join(known_suppliers) or '无'}\n\n"
            f"文件：{file_label}\n内容：\n{payload_text}")
    last_err = None
    for _ in range(3):  # 初次 + 2 次重试
        try:
            data = client.chat_json(SYSTEM_EXTRACT, hint, images=images)
            items = [validate_item(it)[0] for it in (data.get("items") or [])]
            return {"items": items,
                    "email_terms": data.get("email_terms"),
                    "supplier_name": data.get("supplier_name")}
        except (json.JSONDecodeError, LLMError, KeyError, TypeError, AttributeError) as e:
            last_err = e
            hint = f"{hint}\n\n[上次输出无法解析: {e}。请严格只输出一个合法 JSON 对象。]"
    raise LLMError(f"抽取失败 {file_label}: {last_err}")
