"""
中文字符串提取和翻译工具
用于Kotlin Multiplatform项目的字符串国际化
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Set, Optional, Callable
from dataclasses import dataclass
import openai
from lxml import etree as LET
from traceback import print_exc
from httpx import Timeout

@dataclass
class ChineseString:
    """中文字符串数据类"""
    text: str
    file_path: str
    line_number: int
    context: str  # 周围的代码上下文
    resource_name: str = ""  # 生成的资源名
    translation: str = ""  # 英文翻译
    selected: bool = True  # 是否选中进行翻译
    # 统一使用 args：若 len(args)>0 则视为格式化字符串
    args: List[Dict[str, str]] = None  # 可选：参数键值对 [{"name", "value"}]
    module_name: str = ""  # 模块名

    def __post_init__(self):
        if self.args is None:
            self.args = []
        # 自动生成模块名（从文件路径提取）
        if not self.module_name:
            path_parts = Path(self.file_path).parts
            self.module_name = path_parts[0] if path_parts else "common"

    @property
    def unique_id(self) -> str:
        """获取唯一标识符：module_name:原始内容"""
        return f"{self.module_name}:{self.text}"

class ChineseStringExtractor:
    """中文字符串提取器"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        print(f"[初始化] 项目根目录: {project_root}")
        self.ignored_strings: Set[str] = self.load_ignored_strings()
        print(f"[初始化] 已加载 {len(self.ignored_strings)} 个忽略字符串")
        self.existing_resources: Dict[str, str] = self.load_existing_resources()
        print(f"[初始化] 已加载 {len(self.existing_resources)} 个现有资源")
        
        # 中文字符串正则模式
        self.chinese_patterns = [
            r'"([^"]*[\u4e00-\u9fff][^"]*)"',  # 双引号中的中文
            r"'([^']*[\u4e00-\u9fff][^']*)'",  # 单引号中的中文  
        ]
        
        # 已有ResStrings引用的模式
        self.resstrings_pattern = r'ResStrings\.\w+(?:\.format\([^)]*\))?'
        
        # 需要排除的模式
        self.exclude_patterns = [
            r'^\s*//.*',  # 单行注释
            r'^\s*/\*.*?\*/',  # 多行注释开始
            r'Log\.[dwiev]\s*\(',  # 日志输出
            r'println\s*\(',  # println输出
            r'print\s*\(',  # print输出
        ]

    def load_ignored_strings(self) -> Set[str]:
        """加载已忽略的字符串"""
        ignored_file = self.project_root / "ignored_strings.json"
        if ignored_file.exists():
            with open(ignored_file, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        return set()

    def save_ignored_strings(self, ignored: Set[str]):
        """保存忽略的字符串"""
        ignored_file = self.project_root / "ignored_strings.json"
        with open(ignored_file, 'w', encoding='utf-8') as f:
            json.dump(list(ignored), f, ensure_ascii=False, indent=2)

    def load_existing_resources(self) -> Dict[str, str]:
        """加载现有的字符串资源"""
        resources = {}
        
        # 扫描所有模块的strings.xml文件
        for strings_dir in self.project_root.rglob("**/libres/strings"):
            if strings_dir.is_dir():
                for lang_file in strings_dir.glob("strings_*.xml"):
                    try:
                        tree = LET.parse(str(lang_file))
                        root = tree.getroot()
                        for string_elem in root.findall("string"):
                            name = string_elem.get("name")
                            text = string_elem.text or ""
                            if name and self.contains_chinese(text):
                                resources[text] = f"ResStrings.{name}"
                    except LET.XMLSyntaxError:
                        continue
        
        return resources

    def contains_chinese(self, text: str) -> bool:
        """检查文本是否包含中文"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    def extract_strings_from_file(self, file_path: Path) -> List[ChineseString]:
        """从单个文件提取中文字符串"""
        if not file_path.suffix == '.kt':
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            return []

        strings = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines, 1):
            # 跳过注释行和日志输出行
            if any(re.search(pattern, line) for pattern in self.exclude_patterns):
                continue
            
            # 跳过已有ResStrings引用的行
            if re.search(self.resstrings_pattern, line):
                continue
                
            # 提取中文字符串
            for pattern in self.chinese_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    text = match.group(1) if match.groups() else match.group(0)
                    
                    # 检查是否包含中文
                    if not self.contains_chinese(text):
                        continue
                        
                    # 检查是否在忽略列表中
                    if text in self.ignored_strings:
                        continue
                        
                    # 检查是否已有对应的资源
                    if text in self.existing_resources:
                        continue
                    
                    # 获取上下文
                    start_line = max(0, i - 3)
                    end_line = min(len(lines), i + 2)
                    context = '\n'.join(lines[start_line:end_line])
                    
                    # 预构造 args（若存在占位），name=占位为合法标识符则用其，否则使用 argN
                    placeholder_params = self.extract_format_params(text)
                    args_list: List[Dict[str, str]] = []
                    ident_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
                    for idx, expr in enumerate(placeholder_params):
                        expr_str = str(expr).strip()
                        if not expr_str:
                            continue
                        name = expr_str if ident_re.match(expr_str) else f"arg{idx+1}"
                        args_list.append({"name": name, "value": expr_str})

                    chinese_string = ChineseString(
                        text=text,
                        file_path=str(file_path.relative_to(self.project_root).as_posix()),
                        line_number=i,
                        context=context,
                        args=args_list
                    )
                    strings.append(chinese_string)
        
        return strings

    def extract_format_params(self, text: str) -> List[str]:
        """提取格式化参数 {param}"""
        # 支持 Kotlin 字符串中的 ${name} 或 $name 两种形式
        pattern = re.compile(r"\$\{(.+?)\}|\$(\w+)")
        raw_matches = pattern.findall(text)
        # findall 对于两个捕获组会返回 (group1, group2) 的元组列表，这里标准化为纯参数名列表
        names: List[str] = []
        for g1, g2 in raw_matches:
            name = g1 or g2
            if name:
                names.append(name)
        return names

    def extract_all_strings(self, extraction_globs: Optional[List[str]] = None) -> List[ChineseString]:
        """提取项目中所有的中文字符串
        
        Args:
            extraction_globs: 自定义扫描模式列表（glob），如 ["**/*.kt", "**/*.kts"]。
                若不提供，则默认扫描所有 Kotlin 源文件（**/*.kt）。
        """
        print("[开始] 扫描项目中的中文字符串...")
        all_strings = []
        
        # 默认扫描 *.kt 文件
        globs = extraction_globs if extraction_globs else ["**/*.kt"]
        print(f"[扫描] 使用模式: {globs}")
        
        visited: Set[Path] = set()
        file_count = 0
        for pattern in globs:
            for kt_file in self.project_root.rglob(pattern):
                if kt_file in visited:
                    continue
                visited.add(kt_file)
                # 排除常见构建目录
                if any(part in {"build", ".gradle", "node_modules"} for part in kt_file.parts):
                    continue
                file_count += 1
                strings = self.extract_strings_from_file(kt_file)
                if strings:
                    print(f"[提取] {kt_file.relative_to(self.project_root)}: 找到 {len(strings)} 个中文字符串")
                all_strings.extend(strings)
        
        print(f"[扫描完成] 共扫描 {file_count} 个文件，找到 {len(all_strings)} 个中文字符串")
        
        # 去重（基于unique_id，即模块名和文本内容）
        unique_strings = {}
        for s in all_strings:
            unique_id = s.unique_id
            if unique_id not in unique_strings:
                unique_strings[unique_id] = s
        
        if len(unique_strings) != len(all_strings):
            print(f"[去重] 去除 {len(all_strings) - len(unique_strings)} 个重复项，剩余 {len(unique_strings)} 个唯一字符串")
        
        return list(unique_strings.values())

    def generate_resource_name(self, text: str, context: str = "") -> str:
        """生成资源名称"""
        # 移除特殊字符，保留中文、英文和数字
        name = re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)
        # 将空格替换为下划线
        name = re.sub(r'\s+', '_', name.strip())
        # 转换为小写（仅英文部分）
        name = ''.join(c.lower() if c.isascii() else c for c in name)
        # 限制长度
        name = name[:30]
        # 如果名称为空或只有下划线，使用默认名称
        if not name or name.replace('_', '').strip() == '':
            # 基于文本内容生成简单标识符
            name = f"text_{abs(hash(text)) % 100000:05d}"
        return name

    def extract_reference_translations(
        self, 
        source_xml_path: str, 
        target_language: str, 
        target_xml_path: str, 
        limit: int = 10
    ) -> List[Dict[str, str]]:
        """从现有的XML文件中提取参考翻译对照
        
        Args:
            source_xml_path: 源XML文件路径模板，如 "{module_name}/src/commonMain/libres/strings/strings_zh.xml"
            target_language: 目标语言代码，如 "en"
            target_xml_path: 目标XML文件路径模板，如 "{module_name}/src/commonMain/libres/strings/strings_{target_language}.xml"
            limit: 最大提取数量
            
        Returns:
            List[Dict[str, str]]: 翻译对照列表，每个元素包含 source, target 字段
        """
        print(f"[开始] 提取参考翻译对照，目标语言: {target_language}，限制数量: {limit}")
        references = []
        
        try:
            # 扫描所有模块
            scanned_modules = 0
            for module_dir in self.project_root.iterdir():
                

                if not module_dir.is_dir() or module_dir.name.startswith('.'):
                    continue

                # 包含编译的路径跳过
                if any(part in {"build", ".gradle", "node_modules"} for part in module_dir.parts):
                    continue

                scanned_modules += 1
                print(f"[扫描模块] {module_dir.name} ({scanned_modules})")
                
                # 构建实际的XML文件路径
                source_path = self.project_root / source_xml_path.format(module_name=module_dir.name)
                target_path = self.project_root / target_xml_path.format(
                    module_name=module_dir.name, 
                    target_language=target_language
                )
                
                # 检查文件是否存在
                if not source_path.exists() or not target_path.exists():
                    continue
                
                # 解析XML文件
                source_strings = _parse_strings_xml(source_path)
                target_strings = _parse_strings_xml(target_path)
                
                # 提取对照翻译
                found_in_module = 0
                for name, source_text in source_strings.items():
                    if name in target_strings and self.contains_chinese(source_text):
                        target_text = target_strings[name]
                        # 跳过空的或者只有空白字符的翻译
                        if target_text.strip():
                            references.append({
                                'source': source_text,
                                'target': target_text,
                                'resource_name': name,
                                'module': module_dir.name
                            })
                            found_in_module += 1
                            
                            # 达到限制数量时停止
                            if len(references) >= limit:
                                break
                
                if found_in_module > 0:
                    print(f"[找到] 模块 {module_dir.name}: {found_in_module} 对翻译")
                
                # 达到限制数量时停止扫描其他模块
                if len(references) >= limit:
                    break
                    
        except Exception as e:
            print_exc()
            print(f"[错误] 提取参考翻译时出错: {e}")
        
        print(f"[完成] 共提取到 {len(references)} 对参考翻译")
        return references


class TranslationService:
    """翻译服务"""
    
    def __init__(
            self, 
            api_key: str, base_url: str = "", model_name: str = "gpt-4o-mini", 
            custom_prompt: str = "", batch_size: int = 50, reference_translations: str = "", target_language: str = "en"):
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url or None)
        self.model_name = model_name
        self.custom_prompt = custom_prompt
        self.batch_size = batch_size
        self.target_language = target_language
        self.reference_translations = reference_translations

    def translate_batch(self, strings: List[ChineseString]) -> List[Dict]:
        """批量翻译字符串"""
        if not strings:
            return []
            
        print(f"[翻译] 开始翻译 {len(strings)} 个字符串到 {self.target_language}")
        
        # 构建翻译请求
        texts_to_translate = [s.text for s in strings]
    
        prompt = self.custom_prompt.format(
            target_language=self.target_language,
            reference_translations=self.reference_translations,
            source_strings=json.dumps(texts_to_translate, ensure_ascii=False),
        )
        try:
            print(f"[API调用] 使用模型: {self.model_name}, prompt: ")
            print(prompt)
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个专业的软件国际化翻译专家。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                # （total, connect, sock_read, sock_connect）
                timeout=Timeout(120.0, read=120.0, write=20.0, connect=20.0),
                stream=True
            )

            result_text = ""
            i = 0 # 每十次打印一下
            temp_text = ""
            for chunk in response:
                if i % 10 == 0:
                    print("[翻译响应] 接受API响应中：" + temp_text.replace('\n', '\\n'))
                    result_text += temp_text
                    temp_text = ""

                temp_text += chunk.choices[0].delta.content
                i += 1

            result_text += temp_text
            print(f"[翻译响应] 收到API响应，长度: {len(result_text)} 字符，完整内容：")
            print(result_text)
            # 尝试解析JSON
            try:
                result = json.loads(result_text)
                print(f"[翻译成功] 成功解析 {len(result) if isinstance(result, list) else '?'} 个翻译结果")
                return result
            except json.JSONDecodeError:
                print("[解析] JSON解析失败，尝试提取JSON部分")
                # 如果JSON解析失败，尝试提取JSON部分
                json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    print(f"[翻译成功] 提取并解析 {len(result) if isinstance(result, list) else '?'} 个翻译结果")
                    return result
                else:
                    raise ValueError("无法解析翻译结果")
                    
        except Exception as e:
            print(f"[翻译失败] {e}")
            print_exc()
            return []


class StringReplacer:
    """字符串替换器"""
    
    def __init__(self, project_root: str, replacement_script: str = ""):
        self.project_root = Path(project_root)
        # 解析用户脚本，提供两个可选钩子：get_replaced_text 与 get_import_statements
        self._get_replaced_text, self._get_import_statements, self._format_xml_text = self._load_replacement_script(replacement_script)

    def generate_strings_xml_with_template(
        self,
        module_name: str,
        strings: List[ChineseString],
        lang: str,
        xml_path_template: Optional[str]
    ) -> bool:
        """
        使用用户提供的模板生成 strings XML。
        - xml_path_template 示例："{module_name}/src/commonMain/libres/strings/strings_{lang}.xml"
        - 支持占位符：{module_name}、{lang}、{target_language}（与 {lang} 等价）
        """
        print(f"[XML生成] 开始为模块 {module_name} 生成 {lang} 语言的XML文件")
        try:
            if not xml_path_template:
                # 回退到默认路径逻辑
                print("[错误] 请输入合法的 xml_path_template")
                return False

            # 解析模板
            relative = xml_path_template.format(module_name=module_name, lang=lang, target_language=lang)
            xml_file = (self.project_root / relative).resolve()
            print(f"[XML路径] {xml_file}")
            xml_file.parent.mkdir(parents=True, exist_ok=True)

            # 加载现有 XML，尽量保留原有注释与结构
            existing_names: Dict[str, str] = {}
            tree: LET.ElementTree
            if xml_file.exists():
                try:
                    tree = LET.parse(str(xml_file))
                    root = tree.getroot()
                    for string_elem in root.findall("string"):
                        name = string_elem.get("name")
                        text = string_elem.text or ""
                        if name:
                            existing_names[name] = text
                except LET.XMLSyntaxError:
                    # 如果旧文件解析失败，则新建
                    root = LET.Element("resources")
                    tree = LET.ElementTree(root)
            else:
                root = LET.Element("resources")
                tree = LET.ElementTree(root)

            # 仅追加新增项，避免覆盖与删除，最大化保持原有结构/注释
            # 统一缩进控制：
            # - 若将要追加元素，则确保：
            #   1) 若已存在子元素，则把“最后一个现有子元素”的 tail 设为 "\n    "，让下一个元素得到正确缩进；
            #   2) 若不存在子元素，则把 root.text 设为 "\n    "；
            #   3) 对于新追加的元素，除最后一个外 tail 设为 "\n    "，最后一个设为 "\n"，避免 </resources> 前多出空格。
            to_append: List[ChineseString] = []
            for s in strings:
                if s.resource_name and s.resource_name not in existing_names:
                    to_append.append(s)

            print(f"[XML检查] 现有条目: {len(existing_names)}，待添加: {len(to_append)}")
            
            if to_append:
                # 情况1：已有子元素，修正最后一个现有元素的 tail，保证第一个追加元素有缩进
                last_existing_element = None
                for child in reversed(root):
                    if isinstance(getattr(child, 'tag', None), str):  # 仅元素节点
                        last_existing_element = child
                        break
                if last_existing_element is not None:
                    last_existing_element.tail = "\n    "
                else:
                    # 情况2：没有任何子元素，让 root.text 提供初始缩进
                    if root.text is None or root.text.strip() == "":
                        root.text = "\n    "

                # 依次追加元素，并设置合适的 tail
                for idx, s in enumerate(to_append):
                    elem = LET.SubElement(root, "string")
                    elem.set("name", s.resource_name)
                    base_text = s.translation if lang != "zh" else s.text
                    # 通过脚本指定 XML 中占位符格式（LibRes 默认 ${name}；其他模板可定义为 %s 等）
                    if isinstance(s.args, list) and s.args:
                        try:
                            pre_text = base_text
                            base_text = self._format_xml_text(base_text or "", s.args)
                            print(f"format [{pre_text}] with args {s.args} -> {base_text}")
                        except Exception:
                            print("执行自定义 format_xml_text 失败。回退到默认实现")
                            print_exc()
                            # 回退到旧的标准化行为
                            base_text = self._normalize_placeholders(base_text or "", s.args)
                    elem.text = base_text
                    # 最后一个元素 tail 仅为换行，避免 </resources> 前出现多余空格
                    elem.tail = "\n" if idx == len(to_append) - 1 else "\n    "

            # 保存，保留注释，带 XML 声明
            tree.write(
                str(xml_file),
                encoding="utf-8",
                xml_declaration=True,
                pretty_print=True,
            )
            print(f"[XML完成] 成功生成XML文件，新增 {len(to_append)} 个条目")
            return True
        except Exception as e:
            print(f"[XML失败] 生成模板 XML 文件失败: {e}")
            return False

    def replace_strings_in_file_advanced(
        self,
        file_path: Path,
        strings: List[ChineseString],
        module_name: str
    ) -> bool:
        """
        高级替换：使用用户脚本生成替换文本，并按需插入 import（同文件只插入一次）。
        - strings: 列表中的每项需包含 text（原文）、resource_name（目标资源名）、format_params（参数名列表）。
        - module_name: 当前模块名，用于 import 生成。
        """
        print(f"[替换] 开始处理文件: {file_path.relative_to(self.project_root)}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content
            any_replaced = False
            replaced_count = 0

            # 逐条构造替换
            for s in strings:
                if not s.resource_name:
                    continue
                # 根据优先级生成 args 列表：
                # 1) 若 s.args 已由 AI 提供，直接使用（做基本清洗）
                # 2) 否则根据 format_params + arg_names 推导
                args_list: List[Dict[str, str]] = []

                def _clean_arg_item(item: Dict[str, str]) -> Optional[Dict[str, str]]:
                    if not isinstance(item, dict):
                        return None
                    name = str(item.get("name", "")).strip()
                    value = str(item.get("value", "")).strip()
                    if not name:
                        return None
                    if not value:
                        value = name
                    return {"name": name, "value": value}

                if isinstance(s.args, list) and s.args:
                    for it in s.args:
                        cleaned = _clean_arg_item(it)
                        if cleaned:
                            args_list.append(cleaned)
                else:
                    # 从原文中提取占位，自动构造 name=value
                    placeholder_pattern = re.compile(r"\$\{(.+?)\}|\$(\w+)")
                    raw_matches = placeholder_pattern.findall(s.text or "")
                    for idx, (g1, g2) in enumerate(raw_matches):
                        raw_expr = (g1 or g2 or "").strip()
                        if not raw_expr:
                            continue
                        def _is_identifier(candidate: str) -> bool:
                            return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", candidate))
                        final_name = raw_expr if _is_identifier(raw_expr) else f"arg{idx+1}"
                        args_list.append({"name": final_name, "value": raw_expr})

                # 通过用户脚本生成替换表达式（Kotlin 代码片段）
                try:
                    replaced_expr = self._get_replaced_text(s.resource_name, args_list, file_path.absolute().as_posix())
                except Exception:
                    # 回退策略
                    replaced_expr = f"ResStrings.{s.resource_name}"

                # 精确匹配原始文本字面量（单双引号）
                literal_patterns = [
                    f'"{re.escape(s.text)}"',
                    f"'{re.escape(s.text)}'",
                ]
                for patt in literal_patterns:
                    new_content, num = re.subn(patt, replaced_expr, content)
                    if num > 0:
                        content = new_content
                        any_replaced = True
                        replaced_count += num
                        print(f"[替换成功] '{s.text}' -> {s.resource_name} ({num}处)")

            # 如果有替换，尝试插入 import（仅一次）
            if any_replaced:
                try:
                    import_line = self._get_import_statements(module_name, file_path.absolute().as_posix())
                except Exception:
                    import_line = ""

                if import_line and import_line not in content:
                    content = self._insert_import_once(content, import_line)

            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"[替换完成] 文件已更新，共替换 {replaced_count} 处字符串")
                return True
            else:
                print("[替换跳过] 文件无需更改")
                return False
        except Exception as e:
            print(f"[替换失败] {file_path}: {e}")
            return False

    # -------------------- 内部工具 --------------------
    def _load_replacement_script(
        self,
        script: str
    ) -> tuple[
        Callable[[str, List[Dict[str, str]], str], str],
        Callable[[str, str], str],
        Callable[[str, List[Dict[str, str]]], str]
    ]:
        """
        加载用户提供的 Python 脚本，导出：
          - get_replaced_text(res_name: str, args: list[dict], file_path: str) -> str
          - get_import_statements(module_name: str, file_path: str) -> str
        若未提供或解析失败，提供安全的默认实现。
        """
        def _default_get_replaced_text(res_name: str, args: List[Dict[str, str]], file_path: str) -> str:
            if not args:
                return f"ResStrings.{res_name}"
            # 按 Kotlin 命名参数形式拼接：name = (value).toString()
            parts: List[str] = []
            for item in args:
                name = str(item.get("name", "")).strip() or "arg"
                value = str(item.get("value", "")).strip() or name
                parts.append(f"{name} = ({value}).toString()")
            joined = ", ".join(parts)
            return f"ResStrings.{res_name}.format({joined})"

        def _default_get_import_statements(module_name: str, file_path: str) -> str:
            if module_name == "composeApp":
                return "import com.funny.translation.strings.ResStrings"
            return f"import com.funny.translation.{module_name.replace('-', '')}.strings.ResStrings"

        def _default_format_xml_text(text: str, args: List[Dict[str, str]]) -> str:
            """默认用于 LibRes：将占位统一为 ${name} 形式。
            - 支持 ${expr} 与 $ident 两种占位，统一替换为 ${name}
            - 基于 args 中的 name/value 进行标准化
            """
            if not isinstance(args, list) or not args:
                return text or ""
            return self._normalize_placeholders(text or "", args)

        if not script or not script.strip():
            return _default_get_replaced_text, _default_get_import_statements, _default_format_xml_text

        def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            # 仅允许导入正则模块 re
            if name == 're':
                return re
            raise ImportError(f"不允许导入模块: {name}")

        safe_builtins = {
            'str': str, 'dict': dict, 'list': list, 'len': len, 'min': min, 'max': max,
            'enumerate': enumerate, 'sorted': sorted, 'range': range, "isinstance": isinstance,
            "int": int, "float": float,
            '__import__': _safe_import,
        }
        local_vars: Dict[str, object] = {}
        try:
            print("[脚本] 开始解析用户自定义替换脚本，传入的源代码：")
            print(script)
            exec(  # nosec - 用户受信输入，建议仅在本地开发环境使用
                script,
                {'__builtins__': safe_builtins, 're': re},
                local_vars
            )
            get_replaced = local_vars.get('get_replaced_text') or _default_get_replaced_text
            get_imports = local_vars.get('get_import_statements') or _default_get_import_statements
            format_xml = local_vars.get('format_xml_text') or _default_format_xml_text
            # 简单校验可调用
            if not callable(get_replaced):
                get_replaced = _default_get_replaced_text
            if not callable(get_imports):
                get_imports = _default_get_import_statements
            if not callable(format_xml):
                format_xml = _default_format_xml_text
            print("[脚本] 用户脚本解析成功")
            return get_replaced, get_imports, format_xml
        except Exception as e:
            print(f"[脚本] 解析替换脚本失败，使用默认实现: {e}")
            return _default_get_replaced_text, _default_get_import_statements, _default_format_xml_text

    def _insert_import_once(self, content: str, import_line: str) -> str:
        """将 import_line 插入到 Kotlin 文件中：
        - 若已存在相同 import，则不重复插入
        - 优先插在 package 与现有 import 之后；否则插在文件顶部
        """
        if not import_line.endswith('\n'):
            import_line = import_line + '\n'

        if import_line.strip() in content:
            return content

        lines = content.split('\n')
        package_index = -1
        last_import_index = -1
        for idx, line in enumerate(lines):
            if package_index == -1 and line.strip().startswith('package '):
                package_index = idx
            elif line.strip().startswith('import '):
                last_import_index = idx

        insert_at = 0
        if last_import_index >= 0:
            insert_at = last_import_index + 1
        elif package_index >= 0:
            insert_at = package_index + 1

        lines.insert(insert_at, import_line.rstrip('\n'))
        return '\n'.join(lines)

    def _normalize_placeholders(self, text: str, args: List[Dict[str, str]]) -> str:
        """将文本中的占位统一替换为基于 args 的 name 形式。
        - 匹配 ${value} → ${name}
        - 若 value 是合法标识符，同时匹配 $value → $name
        """
        if not text:
            return text
        normalized = text
        for item in args:
            name = str(item.get("name", "")).strip()
            value = str(item.get("value", "")).strip()
            if not name or not value:
                continue
            # 替换 ${value} -> ${name}
            try:
                pattern_braced = re.escape("${" + value + "}")
                normalized = re.sub(pattern_braced, "${" + name + "}", normalized)
            except re.error:
                pass
            # 替换 $value -> $name（仅当 value 是合法标识符）
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
                normalized = re.sub(r"\$" + re.escape(value) + r"\b", "$" + name, normalized)
        return normalized

def _parse_strings_xml(xml_path: Path) -> dict[str, str]:
    """解析 strings_*.xml，返回 name->text 映射。不存在返回空。"""
    try:
        if not xml_path.exists():
            return {}
        tree = LET.parse(str(xml_path))
        root = tree.getroot()
        result = {}
        for string_elem in root.findall("string"):
            name = string_elem.get("name")
            text = string_elem.text or ""
            if name:
                result[name] = text
        print(f"[解析XML] {xml_path.name}: 找到 {len(result)} 个字符串条目")
        return result
    except Exception as e:
        print(f"[解析XML] 解析失败 {xml_path}: {e}")
        return {}