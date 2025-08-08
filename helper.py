"""
中文字符串提取和翻译工具
用于Kotlin Multiplatform项目的字符串国际化
"""

import re
import json
from pathlib import Path
from typing import List, Dict, Set
from dataclasses import dataclass
import openai
from xml.etree import ElementTree as ET
from xml.dom import minidom

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
    format_params: List[str] = None  # 格式化参数列表
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
                        tree = ET.parse(lang_file)
                        root = tree.getroot()
                        for string_elem in root.findall("string"):
                            name = string_elem.get("name")
                            text = string_elem.text or ""
                            if name and self.contains_chinese(text):
                                resources[text] = f"ResStrings.{name}"
                    except ET.ParseError:
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
        return re.findall(r'\{(\w+)\}', text)

    def extract_all_strings(self) -> List[ChineseString]:
        """提取项目中所有的中文字符串"""
        all_strings = []
        
        # 扫描所有Kotlin文件
        for kt_file in self.project_root.rglob("**/*.kt"):
            if "build" in str(kt_file) or ".gradle" in str(kt_file):
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
            target_xml_path: 目标XML文件路径模板，如 "{module_name}/src/commonMain/libres/strings/strings_{target_lang}.xml"
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
                
                # 构建实际的XML文件路径
                source_path = self.project_root / source_xml_path.format(module_name=module_dir.name)
                target_path = self.project_root / target_xml_path.format(
                    module_name=module_dir.name, 
                    target_lang=target_language
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
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)

    def replace_strings_in_file(self, file_path: Path, replacements: Dict[str, str]) -> bool:
        """在文件中替换字符串"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # 执行替换
            for old_text, new_text in replacements.items():
                # 精确匹配字符串字面量
                patterns = [
                    f'"{re.escape(old_text)}"',
                    f"'{re.escape(old_text)}'"
                ]
                
                for pattern in patterns:
                    content = re.sub(pattern, f'ResStrings.{new_text}', content)
            
            # 只有内容改变时才写入
            if content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                return True
                
        except Exception as e:
            print(f"替换文件 {file_path} 失败: {e}")
            return False
        
        return False

    def generate_strings_xml(self, module_path: Path, strings: List[ChineseString], lang: str = "zh") -> bool:
        """生成strings.xml文件"""
        strings_dir = module_path / "src" / "commonMain" / "libres" / "strings"
        strings_dir.mkdir(parents=True, exist_ok=True)
        
        xml_file = strings_dir / f"strings_{lang}.xml"
        
        # 创建XML文档
        root = ET.Element("resources")
        
        # 加载现有的strings（如果存在）
        existing_strings = {}
        if xml_file.exists():
            try:
                tree = ET.parse(xml_file)
                existing_root = tree.getroot()
                for string_elem in existing_root.findall("string"):
                    name = string_elem.get("name")
                    text = string_elem.text or ""
                    if name:
                        existing_strings[name] = text
            except ET.ParseError:
                pass
        
        # 添加现有字符串
        for name, text in existing_strings.items():
            string_elem = ET.SubElement(root, "string")
            string_elem.set("name", name)
            string_elem.text = text
        
        # 添加新字符串
        for s in strings:
            if s.resource_name and s.resource_name not in existing_strings:
                string_elem = ET.SubElement(root, "string")
                string_elem.set("name", s.resource_name)
                text = s.translation if lang == "en" else s.text
                string_elem.text = text
        
        # 格式化并保存XML
        rough_string = ET.tostring(root, 'utf-8')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="    ", encoding='utf-8').decode('utf-8')
        
        # 移除空行
        lines = [line for line in pretty_xml.split('\n') if line.strip()]
        pretty_xml = '\n'.join(lines)
        
        try:
            with open(xml_file, 'w', encoding='utf-8') as f:
                f.write(pretty_xml)
            return True
        except Exception as e:
            print(f"生成XML文件失败: {e}")
            return False

def _parse_strings_xml(xml_path: Path) -> dict[str, str]:
    """解析 strings_*.xml，返回 name->text 映射。不存在返回空。"""
    try:
        if not xml_path.exists():
            return {}
        tree = ET.parse(xml_path)
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