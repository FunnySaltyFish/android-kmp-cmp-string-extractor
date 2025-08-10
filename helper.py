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
    is_format_string: bool = False  # 是否包含格式化参数
    format_params: List[str] = None  # 格式化参数名称列表（如 ["count", "name"]）
    module_name: str = ""  # 模块名

    def __post_init__(self):
        if self.format_params is None:
            self.format_params = []
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
        self.ignored_strings: Set[str] = self.load_ignored_strings()
        self.existing_resources: Dict[str, str] = self.load_existing_resources()
        
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
                    
                    # 检查是否是格式化字符串
                    format_params = self.extract_format_params(text)
                    is_format_string = len(format_params) > 0
                    
                    chinese_string = ChineseString(
                        text=text,
                        file_path=str(file_path.relative_to(self.project_root).as_posix()),
                        line_number=i,
                        context=context,
                        is_format_string=is_format_string,
                        format_params=format_params
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
        all_strings = []
        
        # 默认扫描 *.kt 文件
        globs = extraction_globs if extraction_globs else ["**/*.kt"]
        visited: Set[Path] = set()
        for pattern in globs:
            for kt_file in self.project_root.rglob(pattern):
                if kt_file in visited:
                    continue
                visited.add(kt_file)
                # 排除常见构建目录
                if any(part in {"build", ".gradle", "node_modules"} for part in kt_file.parts):
                    continue
                strings = self.extract_strings_from_file(kt_file)
                all_strings.extend(strings)
        
        # 去重（基于unique_id，即模块名和文本内容）
        unique_strings = {}
        for s in all_strings:
            unique_id = s.unique_id
            if unique_id not in unique_strings:
                unique_strings[unique_id] = s
        
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
        references = []
        
        try:
            # 扫描所有模块
            for module_dir in self.project_root.iterdir():
                

                if not module_dir.is_dir() or module_dir.name.startswith('.'):
                    continue

                # 包含编译的路径跳过
                if any(part in {"build", ".gradle", "node_modules"} for part in module_dir.parts):
                    continue

                print("当前扫描目录：", module_dir)
                
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
                            
                            # 达到限制数量时停止
                            if len(references) >= limit:
                                break
                
                # 达到限制数量时停止扫描其他模块
                if len(references) >= limit:
                    break
                    
        except Exception as e:
            print_exc()
            print(f"提取参考翻译时出错: {e}")
        
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
            
        # 构建翻译请求
        texts_to_translate = [s.text for s in strings]
    
        prompt = self.custom_prompt.format(
            target_language=self.target_language,
            reference_translations=self.reference_translations,
            source_strings=json.dumps(texts_to_translate, ensure_ascii=False),
        )
        try:
            print("prompt: ", prompt)
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一个专业的软件国际化翻译专家。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            result_text = response.choices[0].message.content
            # 尝试解析JSON
            try:
                return json.loads(result_text)
            except json.JSONDecodeError:
                # 如果JSON解析失败，尝试提取JSON部分
                json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                else:
                    raise ValueError("无法解析翻译结果")
                    
        except Exception as e:
            print(f"翻译失败: {e}")
            return []


class StringReplacer:
    """字符串替换器"""
    
    def __init__(self, project_root: str, replacement_script: str = ""):
        self.project_root = Path(project_root)
        # 解析用户脚本，提供两个可选钩子：get_replaced_text 与 get_import_statements
        self._get_replaced_text, self._get_import_statements = self._load_replacement_script(replacement_script)

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
        try:
            if not xml_path_template:
                # 回退到默认路径逻辑
                print("请输入合法的 xml_path_template")
                return False

            # 解析模板
            relative = xml_path_template.format(module_name=module_name, lang=lang, target_language=lang)
            xml_file = (self.project_root / relative).resolve()
            xml_file.parent.mkdir(parents=True, exist_ok=True)

            # 加载现有 XML，尽量保留原有注释与结构
            existing_names: Dict[str, str] = {}
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
            for s in strings:
                if s.resource_name and s.resource_name not in existing_names:
                    elem = LET.SubElement(root, "string")
                    elem.set("name", s.resource_name)
                    elem.text = s.translation if lang != "zh" else s.text

            # 保存，保留注释，带 XML 声明
            tree.write(
                str(xml_file),
                encoding="utf-8",
                xml_declaration=True,
                pretty_print=True
            )
            return True
        except Exception as e:
            print(f"生成模板 XML 文件失败: {e}")
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
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content
            any_replaced = False

            # 逐条构造替换
            for s in strings:
                if not s.resource_name:
                    continue
                # 根据格式化参数构造 args（假设变量名与参数名一致）
                args_map: Dict[str, str] = {}
                if s.format_params:
                    for name in s.format_params:
                        if isinstance(name, (list, tuple)) and len(name) == 2:
                            # 兼容旧格式返回的 (g1, g2)
                            pname = name[0] or name[1]
                        else:
                            pname = name
                        if pname:
                            args_map[str(pname)] = str(pname)

                # 通过用户脚本生成替换表达式（Kotlin 代码片段）
                try:
                    replaced_expr = self._get_replaced_text(s.resource_name, args_map)
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

            # 如果有替换，尝试插入 import（仅一次）
            if any_replaced:
                try:
                    import_line = self._get_import_statements(module_name, file_path.name)
                except Exception:
                    import_line = ""

                if import_line and import_line not in content:
                    content = self._insert_import_once(content, import_line)

            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True
            return False
        except Exception as e:
            print(f"高级替换失败 {file_path}: {e}")
            return False

    # -------------------- 内部工具 --------------------
    def _load_replacement_script(
        self,
        script: str
    ) -> tuple[Callable[[str, Dict[str, str]], str], Callable[[str, str], str]]:
        """
        加载用户提供的 Python 脚本，导出：
          - get_replaced_text(res_name: str, args: dict[str, str]) -> str
          - get_import_statements(module_name: str, file_name: str) -> str
        若未提供或解析失败，提供安全的默认实现。
        """
        def _default_get_replaced_text(res_name: str, args: Dict[str, str]) -> str:
            if not args:
                return f"ResStrings.{res_name}"
            # 默认按照 Kotlin named args 的形式拼接
            joined = ", ".join([f"{k} = ({v}).toString()" for k, v in args.items()])
            return f"ResStrings.{res_name}.format({joined})"

        def _default_get_import_statements(module_name: str, file_name: str) -> str:
            return f"import com.funny.translation.{module_name}.strings.ResString"

        if not script or not script.strip():
            return _default_get_replaced_text, _default_get_import_statements

        safe_builtins = {
            'str': str, 'dict': dict, 'list': list, 'len': len, 'min': min, 'max': max,
            'enumerate': enumerate, 'sorted': sorted, 'range': range
        }
        local_vars: Dict[str, object] = {}
        try:
            exec(  # nosec - 用户受信输入，建议仅在本地开发环境使用
                script,
                {'__builtins__': safe_builtins},
                local_vars
            )
            get_replaced = local_vars.get('get_replaced_text') or _default_get_replaced_text
            get_imports = local_vars.get('get_import_statements') or _default_get_import_statements
            # 简单校验可调用
            if not callable(get_replaced):
                get_replaced = _default_get_replaced_text
            if not callable(get_imports):
                get_imports = _default_get_import_statements
            return get_replaced, get_imports
        except Exception as e:
            print(f"解析替换脚本失败，使用默认实现: {e}")
            return _default_get_replaced_text, _default_get_import_statements

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
        return result
    except Exception:
        return {}