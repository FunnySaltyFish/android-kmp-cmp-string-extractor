// 测试文件：用于验证中文字符串提取功能

package com.funny.test

class TestStrings {
    
    fun simpleStrings() {
        val message = "这是一个简单的中文字符串"
        val title = "标题"
        val description = '单引号中的中文'
    }
    
    fun formatStrings() {
        val userMessage = "用户{name}登录成功"
        val errorMsg = "错误代码：{code}，错误信息：{message}"
        val template = "欢迎{username}，您有{count}条新消息"
    }
    
    fun mixedStrings() {
        val mixed1 = "Hello 你好 World"
        val mixed2 = "价格：$100"
        val mixed3 = "版本 v1.2.3 已发布"
    }
    
    fun existingResStrings() {
        val existing1 = ResStrings.login_success
        val existing2 = ResStrings.error_message.format(code = 404)
        val existing3 = ResStrings.welcome_text.format(name = "用户")
    }
    
    fun shouldIgnore() {
        // 这是注释中的中文，应该被忽略
        Log.d("TAG", "这是日志输出中的中文，应该被忽略")
        println("这是打印输出中的中文，应该被忽略")
        
        /* 
         * 多行注释中的中文
         * 也应该被忽略
         */
    }
    
    fun edgeCases() {
        val empty = ""
        val englishOnly = "This is English only"
        val numbersOnly = "12345"
        val symbols = "!@#$%^&*()"
        val special = "中文\n换行\t制表符"
    }
    
    companion object {
        const val CONSTANT_STRING = "常量字符串"
        private val PRIVATE_STRING = "私有字符串"
    }
}