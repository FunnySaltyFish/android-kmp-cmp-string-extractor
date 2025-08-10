#!/usr/bin/env python3
"""
测试新功能：自动提取参考翻译
"""

import json
from pathlib import Path
from helper import ChineseStringExtractor

def test_extract_references():
    """测试自动提取参考翻译功能"""
    print("测试自动提取参考翻译功能...")
    
    # 使用实际的项目路径
    project_path = "D:/projects/kotlin/Transtation/Transtation-KMP"
    
    try:
        extractor = ChineseStringExtractor(project_path)
        
        # 测试提取参考翻译
        references = extractor.extract_reference_translations(
            source_xml_path="{module_name}/src/commonMain/libres/strings/strings_zh.xml",
            target_language="en",
            target_xml_path="{module_name}/src/commonMain/libres/strings/strings_en.xml",
            limit=10
        )
        
        print(f"成功提取了 {len(references)} 条参考翻译：")
        for i, ref in enumerate(references, 1):
            print(f"{i}. {ref['source']} -> {ref['target']} (模块: {ref['module']}, 资源名: {ref['resource_name']})")
        
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        return False

def test_config_validation():
    """测试配置验证"""
    print("\n测试配置验证...")
    
    test_configs = [
        {
            "name": "默认配置",
            "source_xml_path": "{module_name}/src/commonMain/libres/strings/strings_zh.xml",
            "target_language": "en",
            "target_xml_path": "{module_name}/src/commonMain/libres/strings/strings_{target_language}.xml"
        },
        {
            "name": "自定义配置",
            "source_xml_path": "{module_name}/src/libres/strings_zh.xml",
            "target_language": "ja",
            "target_xml_path": "{module_name}/src/libres/strings_{target_language}.xml"
        }
    ]
    
    for config in test_configs:
        print(f"测试 {config['name']}:")
        print(f"  源文件路径模板: {config['source_xml_path']}")
        print(f"  目标语言: {config['target_language']}")
        print(f"  目标文件路径模板: {config['target_xml_path']}")
        
        # 模拟路径替换
        module_name = "composeApp"
        source_path = config['source_xml_path'].format(module_name=module_name)
        target_path = config['target_xml_path'].format(
            module_name=module_name,
            target_language=config['target_language']
        )
        
        print(f"  实际源文件路径: {source_path}")
        print(f"  实际目标文件路径: {target_path}")
        print()

if __name__ == "__main__":
    print("=== 新功能测试 ===")
    
    # 测试配置验证
    test_config_validation()
    
    # 测试自动提取功能
    success = test_extract_references()
    
    if success:
        print("\n✅ 所有测试通过！")
    else:
        print("\n❌ 测试失败！")