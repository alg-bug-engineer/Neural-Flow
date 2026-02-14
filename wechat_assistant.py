#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号协作助手 - 基于 Kimi 2.5 API

功能：
    - 阅读 articles 目录下的文档
    - 智能分析并选择写作切入点
    - 生成具有自媒体风格的公众号文章（去 AI 化）
    - 调用即梦 API 生成配图/插图
    - 输出完整文章到 posts 目录

使用示例:
    python wechat_assistant.py                          # 自动选择文章生成
    python wechat_assistant.py --article "文章标题"      # 指定源文章
    python wechat_assistant.py --style "犀利"            # 指定写作风格
    python wechat_assistant.py --no-image               # 不生成配图

环境变量:
    KIMI_API_KEY: Kimi API Key (必需)
    JIMENG_TOKEN: 即梦 session token (可选，用于生成配图)
    JIMENG_BASE_URL: 即梦 API 地址 (默认: http://localhost:5100)
"""

import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from openai import OpenAI

# Add project root to path to allow absolute imports from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.utils.logger import get_logger
from src.constants import ARTICLES_DIR, POSTS_DIR, IMAGES_DIR, SRC_DIR

# 加载 .env 文件
load_dotenv()

# ========== 初始化 ==========
logger = get_logger(__name__)

# ============== 配置常量 ==============



# Kimi API 配置
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL = "kimi-k2.5"  # Kimi 2.5 模型

# 写作风格模板
WRITING_STYLES = {
    "犀利": {
        "tone": "犀利直接，敢于吐槽，不回避争议",
        "characteristics": ["开门见山", "观点鲜明", "敢说真话", "略带批判性"],
        "phrases": ["说实话", "说白了", "别急着杠", "这事没那么复杂", "我看未必"],
        "avoid": ["值得注意的是", "让我们来看一下", "不可否认的是", "总而言之"]
    },
    "亲和": {
        "tone": "亲切随和，像朋友聊天一样自然",
        "characteristics": ["口语化", "拉近距离", "分享感", "轻松幽默"],
        "phrases": ["哈喽大家", "最近发现", "说实话", "你们有没有发现", "我觉得吧"],
        "avoid": ["值得注意的是", "本文旨在", "综上所述", "研究表明"]
    },
    "专业": {
        "tone": "专业但不刻板，有技术深度的同时保持可读性",
        "characteristics": ["技术细节准确", "深入浅出", "有行业洞察", "实用导向"],
        "phrases": ["从技术角度看", "实际体验下来", "核心逻辑是", "说白了", "实测发现"],
        "avoid": ["值得注意的是", "让我们来看一下", "随着...的发展", "众所周知"]
    },
    "故事": {
        "tone": "讲故事风格，用叙事带出观点",
        "characteristics": ["场景化", "有代入感", "情节推进", "情感共鸣"],
        "phrases": ["前几天", "有个朋友问我", "当时我就懵了", "后来我发现", "你猜怎么着"],
        "avoid": ["值得注意的是", "本文将", "综上所述", "从理论层面分析"]
    }
}

# 默认系统提示词（去 AI 化核心）
DEAI_SYSTEM_PROMPT = """你是一位资深的 AI 领域自媒体博主，名叫"芝士AI吃鱼"。你的任务是写公众号文章，风格要求：

【绝对禁止的 AI 腔】
- ❌ "值得注意的是..."
- ❌ "让我们来看一下..."
- ❌ "不可否认的是..."
- ❌ "随着 XX 的发展..."
- ❌ "综上所述/总而言之..."
- ❌ "本文旨在探讨..."
- ❌ 任何套话、废话、正确的废话

【写作原则】
1. 像真人说话，有情绪、有态度、有观点
2. 开头要抓人，可以是一个问题、一个场景、一个吐槽
3. 中间要有料，有细节、有分析、有你的判断
4. 结尾要有余味，可以留一个问题、一句金句、一个观点
5. 用短句、用口语、用网络流行语（适度）
6. 适当使用 emoji，但不要过度
7. 段落要短，手机阅读友好

【内容定位】
- 关注 AI、大模型、Agent、RAG 等前沿技术
- 既有新闻解读，也有技术分析，还有实用教程
- 对大厂动态保持敏感，对技术趋势有独到见解
- 不盲从，有独立判断

【输出格式】
- 标题：要有吸引力，带点情绪或悬念
- 正文：Markdown 格式
- 配图提示：在文章中用 [配图: 描述] 标记需要插图的位置
- 结尾：作者署名和一句简短的话
"""


@dataclass
class SourceArticle:
    """源文章数据结构"""
    title: str
    content: str
    file_path: Path
    source_url: Optional[str] = None
    
    def summary(self, max_length: int = 500) -> str:
        """获取内容摘要"""
        content = re.sub(r'!\[.*?\]\(.*?\)', '', self.content)  # 移除图片
        content = re.sub(r'#+ ', '', content)  # 移除标题标记
        content = content.replace('\n', ' ').strip()
        return content[:max_length] + "..." if len(content) > max_length else content


class KimiClient:
    """Kimi API 客户端"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("KIMI_API_KEY")
        if not self.api_key:
            raise ValueError("请提供 Kimi API Key 或设置 KIMI_API_KEY 环境变量")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=KIMI_BASE_URL,
        )
        self.model = KIMI_MODEL
        
    def chat(self, messages: List[Dict[str, str]], temperature: float = 1) -> str:
        """调用 Kimi 聊天接口"""
        try:
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=8000,
            )
            return completion.choices[0].message.content
        except Exception as e:
            raise Exception(f"Kimi API 调用失败: {e}")


class JimengImageGenerator:
    """即梦图片生成器"""
    
    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None):
        self.token = token or os.environ.get("JIMENG_TOKEN")
        # 使用 jimeng_cli.py 的默认端口 6667，不传 --base-url 时使用
        self.base_url = base_url or "http://localhost:6667"
        
    def is_available(self) -> bool:
        """检查是否可用"""
        return bool(self.token)
    
    def generate_image(self, prompt: str, output_path: str, ratio: str = "16:9") -> Optional[str]:
        """生成图片并保存"""
        if not self.token:
            logger.warning("未配置 JIMENG_TOKEN，跳过图片生成")
            return None
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"创建目录: {output_dir}")
        
        # 构建命令 - 使用绝对路径确保在任何工作目录都能执行
        # 注意: --token 和 --base-url 是全局参数，必须放在子命令 text2img 之前
        jimeng_cli_path = SRC_DIR / 'jimeng' / 'jimeng_cli.py'
        output_filename = os.path.basename(output_path)
        cmd = [
            sys.executable, jimeng_cli_path,
            "--token", self.token,
            "text2img", prompt,
            "--ratio", ratio,
            "--resolution", "2k",
            "--download",
            "--output", output_filename  # 只使用文件名，cwd 会处理目录
        ]
        # 只有非默认 base_url 时才添加该参数
        if self.base_url != "http://localhost:6667":
            cmd.insert(3, "--base-url")
            cmd.insert(4, self.base_url)
        
        try:
            logger.info(f"正在生成图片: {prompt[:50]}...")
            logger.info(f"   目标路径: {output_path}")
            
            # 使用目标目录作为工作目录执行命令
            # 这样 jimeng_cli.py 下载的图片会保存在正确的位置
            cwd = output_dir if output_dir else "."
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=cwd)
            
            logger.info(f"   命令返回码: {result.returncode}")
            if result.stdout:
                logger.info(f"   输出: {result.stdout[:500]}")
            if result.stderr:
                logger.warning(f"   错误: {result.stderr[:500]}")
            
            if result.returncode == 0:
                # jimeng_cli.py 生成多张图片时会添加序号后缀 _1, _2, _3, _4
                # 查找生成的文件（优先返回第一张）
                output_filename = os.path.basename(output_path)
                base_filename = output_filename.replace('.webp', '')
                
                # 首先检查带序号的文件（jimeng 默认生成4张）
                for ext in ['.webp', '.jpg', '.png']:
                    first_image = os.path.join(cwd, f"{base_filename}_1{ext}")
                    if os.path.exists(first_image):
                        # 移动到目标路径
                        if first_image != output_path:
                            import shutil
                            shutil.move(first_image, output_path)
                            # 清理其他序号的文件（可选）
                            for i in range(2, 5):
                                other_file = os.path.join(cwd, f"{base_filename}_{i}{ext}")
                                if os.path.exists(other_file):
                                    os.remove(other_file)
                                    logger.info(f"   🗑️  清理多余文件: {os.path.basename(other_file)}")
                        logger.info(f"图片生成成功: {output_path}")
                        return output_path
                
                # 再检查不带序号的文件
                for ext in ['.webp', '.jpg', '.png']:
                    possible_path = f"{output_path.replace('.webp', '')}{ext}"
                    if os.path.exists(possible_path):
                        logger.info(f"图片生成成功: {possible_path}")
                        return possible_path
                
                logger.warning(f"未找到生成的图片文件，预期路径: {output_path}")
                logger.warning(f"   检查目录内容: {os.listdir(cwd) if os.path.exists(cwd) else '目录不存在'}")
                return None
            else:
                logger.error(f"图片生成失败: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"图片生成异常: {e}", exc_info=True)
            return None


class WeChatArticleAssistant:
    """公众号文章协作助手"""
    
    def __init__(self, style: str = "犀利"):
        self.style = style
        self.kimi = None
        self.jimeng = JimengImageGenerator()
        self.style_config = WRITING_STYLES.get(style, WRITING_STYLES["犀利"])
    
    def _ensure_kimi(self):
        """确保 KimiClient 已初始化"""
        if self.kimi is None:
            self.kimi = KimiClient()
        
        # 确保目录存在
        POSTS_DIR.mkdir(exist_ok=True)
        IMAGES_DIR.mkdir(exist_ok=True)
    
    def list_source_articles(self) -> List[SourceArticle]:
        """列出所有源文章"""
        articles = []
        
        if not ARTICLES_DIR.exists():
            logger.warning(f"文章目录不存在: {ARTICLES_DIR}")
            return articles
        
        for file_path in list(ARTICLES_DIR.glob("*.md")) + list(ARTICLES_DIR.glob("*.markdown")):
            content = file_path.read_text(encoding="utf-8")
            title = self._extract_title(content) or file_path.stem
            
            # 提取原文链接
            source_url = None
            for line in content.split('\n'):
                if '原文链接:' in line or '原文链接：' in line:
                    match = re.search(r'https?://\S+', line)
                    if match:
                        source_url = match.group(0)
                        break
            
            articles.append(SourceArticle(
                title=title,
                content=content,
                file_path=file_path,
                source_url=source_url
            ))
        
        return articles
    
    def _extract_title(self, content: str) -> Optional[str]:
        """从 Markdown 内容中提取标题"""
        lines = content.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line.startswith('# '):
                return line[2:].strip()
        return None
    
    def analyze_and_select_angle(self, article: SourceArticle) -> Dict:
        """分析文章并选择写作角度"""
        
        prompt = f"""请分析以下 AI 领域的新闻/技术文章，并给出 3-5 个适合公众号写作的角度。

【源文章标题】
{article.title}

【源文章摘要】
{article.summary(800)}

【分析要求】
1. 提取核心信息点
2. 判断新闻价值和热度
3. 找出最有话题性的切入点
4. 考虑读者可能关心的角度

请按以下格式返回（JSON）：
{{
    "core_info": "核心信息总结",
    "angles": [
        {{
            "title": "角度标题",
            "hook": "吸引人的开头思路",
            "focus": "这个角度的侧重点",
            "audience": "适合什么读者",
            "score": "热度评分 1-10"
        }}
    ],
    "recommendation": "推荐选择哪个角度及原因"
}}"""

        messages = [
            {"role": "system", "content": "你是一位资深的内容策划，擅长从新闻中挖掘最有价值的写作角度。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            self._ensure_kimi()
            response = self.kimi.chat(messages, temperature=0.7)
            # 提取 JSON 部分
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            logger.error(f"分析文章失败: {e}")
        
        # 返回默认分析
        return {
            "core_info": article.summary(200),
            "angles": [{"title": "新闻解读", "hook": "直接报道", "focus": "核心信息", "score": "7"}],
            "recommendation": "新闻解读"
        }
    
    def generate_article(self, article: SourceArticle, angle: Dict, 
                         word_count: int = 1500) -> str:
        """生成公众号文章"""
        
        style_desc = f"""
【写作风格】{self.style}
【语气特点】{self.style_config['tone']}
【常用表达】{', '.join(self.style_config['phrases'])}
【绝对禁止】{', '.join(self.style_config['avoid'])}
"""
        
        prompt = f"""基于以下源文章和选定的写作角度，创作一篇公众号文章。

{style_desc}

【源文章标题】
{article.title}

【源文章内容】
{article.content}

【选定的写作角度】
- 角度: {angle.get('title', '技术解读')}
- 切入点: {angle.get('hook', '从实际应用出发')}
- 侧重点: {angle.get('focus', '技术亮点分析')}

【写作要求】
1. 字数: {word_count} 字左右
2. 开头要抓人，直接入题，不要废话
3. 内容要有你的观点和判断，不要只是复述
4. 适当使用小标题，结构清晰
5. 在需要配图的地方用 [配图: 描述] 标记
6. 结尾要有作者态度和一句金句
7. 全程保持"{self.style}"风格

【输出格式】
直接输出 Markdown 格式的文章，包含：
- 主标题（带 #，小于 20 个字）
- 正文
- 作者署名
"""

        messages = [
            {"role": "system", "content": DEAI_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"正在生成文章，请稍候...")
        self._ensure_kimi()
        return self.kimi.chat(messages, temperature=0.8)
    
    def extract_image_prompts(self, content: str) -> List[str]:
        """提取文章中的配图提示"""
        pattern = r'\[配图[:：]\s*([^\]]+)\]'
        matches = re.findall(pattern, content)
        return matches
    
    def generate_images(self, prompts: List[str], article_title: str) -> Dict[str, str]:
        """为文章生成配图"""
        if not self.jimeng.is_available():
            logger.warning("即梦 API 未配置，跳过图片生成")
            logger.warning(f"   JIMENG_TOKEN 是否设置: {bool(os.environ.get('JIMENG_TOKEN'))}")
            return {}
        
        # 确保图片目录存在
        article_slug = self._slugify(article_title)[:30]
        img_dir = IMAGES_DIR / article_slug
        img_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"图片保存目录: {img_dir}")
        
        image_map = {}
        
        for i, prompt in enumerate(prompts, 1):
            logger.info(f"\n[{i}/{len(prompts)}] 处理配图: {prompt[:40]}...")
            # 增强提示词，使其更适合封面/插图
            enhanced_prompt = self._enhance_image_prompt(prompt)
            output_path = str(img_dir / f"image_{i}.webp")
            logger.info(f"   增强提示词: {enhanced_prompt[:60]}...")
            logger.info(f"   输出路径: {output_path}")
            
            result = self.jimeng.generate_image(enhanced_prompt, output_path, ratio="16:9")
            if result:
                image_map[f"[配图: {prompt}]"] = result
                logger.info(f"   ✅ 成功添加到映射: {result}")
            else:
                logger.warning(f"   生成失败，跳过此配图")
        
        logger.info(f"\n📊 配图生成统计: 成功 {len(image_map)}/{len(prompts)}")
        return image_map
    
    def _convert_to_english_prompt(self, prompt: str) -> str:
        """将中文提示词转换为英文描述，避免即梦渲染中文错乱
        
        使用关键词映射和模式匹配直接生成英文提示词，不调用 API
        """
        # 中文到英文的关键词映射表
        keyword_map = {
            # 技术相关
            'AI': 'AI',
            '人工智能': 'AI',
            '模型': 'model',
            '大模型': 'large language model',
            '通用大模型': 'general LLM',
            '技术': 'technology',
            '代码': 'code',
            '编程': 'programming',
            '数据': 'data',
            '算法': 'algorithm',
            '神经网络': 'neural network',
            '架构': 'architecture',
            '界面': 'interface',
            '系统': 'system',
            '软件': 'software',
            '硬件': 'hardware',
            '云端': 'cloud',
            '本地': 'local',
            '端云': 'edge-cloud',
            '部署': 'deployment',
            '开源': 'open source',
            '订阅': 'subscription',
            '免费': 'free',
            '收费': 'paid',
            '价格': 'price',
            '成本': 'cost',
            '对比': 'comparison',
            ' versus ': ' vs ',
            ' vs ': ' versus ',
            '左边': 'left side',
            '右边': 'right side',
            '左侧': 'left',
            '右侧': 'right',
            '前后': 'before and after',
            '速度': 'speed',
            '高速': 'high-speed',
            '快速': 'fast',
            '慢速': 'slow',
            '慢吞吞': 'slow loading',
            '加载': 'loading',
            '运行': 'running',
            '运转': 'operating',
            '流水线': 'pipeline',
            '工作流': 'workflow',
            '流程': 'process flow',
            '操作': 'operation',
            '自动化': 'automation',
            '智能': 'intelligent',
            '协同': 'collaboration',
            '模式': 'mode',
            '工作模式': 'working mode',
            '机器人': 'robot',
            '代理': 'agent',
            '大脑': 'brain',
            '核心': 'core',
            '窗口': 'window',
            '上下文': 'context',
            '长上下文': 'long context',
            '稀疏': 'sparse',
            '参数': 'parameters',
            'Token': 'token',
            '预测': 'prediction',
            '推理': 'inference',
            '生成': 'generation',
            '训练': 'training',
            
            # 公司名称/品牌（用描述性词汇替代）
            'OpenAI': 'Open AI',
            'ChatGPT': 'AI assistant',
            'GPT-4': 'advanced AI model',
            'GPT': 'AI model',
            'Claude': 'AI assistant',
            '阶跃星辰': 'Chinese AI company',
            'Step': 'Step',
            'Flash': 'Flash',
            'DeepSeek': 'open source AI',
            'Llama': 'open source LLM',
            'Qwen': 'multilingual AI',
            '字节': 'tech giant',
            '阿里': 'tech company',
            '百度': 'search engine AI',
            '腾讯': 'tech conglomerate',
            '华为': 'tech corporation',
            '苹果': 'technology company',
            'Google': 'search giant',
            'Meta': 'social media tech',
            'Microsoft': 'software giant',
            'NVIDIA': 'GPU manufacturer',
            
            # 视觉描述
            '背景': 'background',
            '主题': 'theme',
            '插图': 'illustration',
            '图标': 'icon',
            '图表': 'chart',
            '示意图': 'diagram',
            '屏幕': 'screen',
            '显示器': 'monitor',
            '手机': 'smartphone',
            '电脑': 'computer',
            '笔记本': 'laptop',
            '服务器': 'server',
            '芯片': 'chip',
            '电路': 'circuit',
            '网络': 'network',
            '连接': 'connection',
            '光线': 'light rays',
            '发光': 'glowing',
            '动态': 'dynamic',
            '静态': 'static',
            '抽象': 'abstract',
            '概念': 'concept',
            '未来': 'futuristic',
            '科技感': 'tech-style',
            '现代': 'modern',
            '简洁': 'clean',
            '大气': 'atmospheric',
            '高清': 'high quality',
            '精致': 'elegant',
            '细腻': 'fine detailed',
            '配色': 'color scheme',
            '蓝色调': 'blue tones',
            '紫色调': 'purple tones',
            '金色调': 'golden tones',
            '渐变': 'gradient',
            '深色': 'dark',
            '浅色': 'light',
            
            # 场景
            '城市': 'city',
            '未来城市': 'futuristic city',
            '办公室': 'office',
            '实验室': 'laboratory',
            '数据中心': 'data center',
            '数字': 'digital',
            '虚拟': 'virtual',
            '现实': 'reality',
            '空间': 'space',
            '3D': '3D',
            '立体': 'three-dimensional',
            '平面': 'flat design',
            '网页': 'webpage',
            '页面': 'page',
            '网站': 'website',
            'GitHub': 'code platform',
            
            # 动作/状态
            '展示': 'showing',
            '呈现': 'presenting',
            '突出': 'highlighting',
            '强调': 'emphasizing',
            '包含': 'including',
            '带有': 'with',
            '使用': 'using',
            '通过': 'through',
            '作为': 'as',
            '成为': 'becoming',
            
            # 其他
            '文章': 'article',
            '封面': 'cover',
            '公众号': 'blog',
            '适合': 'suitable for',
            '用于': 'for',
            '图': 'image',
            '图片': 'image',
            '概念图': 'concept art',
            '效果图': 'rendering',
            '照片': 'photo',
            '摄影': 'photography',
            
            # 数字和单位
            '美元': 'USD',
            '元': 'yuan',
            '月': 'month',
            '年': 'year',
            '天': 'day',
            '小时': 'hour',
            '分钟': 'minute',
            '秒': 'second',
            '次': 'times',
            '个': '',
            '张': '',
            
            # 符号和标点
            '、': ',',
            '，': ',',
            '。': '.',
            '！': '!',
            '？': '?',
            '：': ':',
            '；': ';',
            '"': '"',
            '"': '"',
            ''': "'",
            ''': "'",
            '（': '(',
            '）': ')',
            '【': '[',
            '】': ']',
            '《': '<',
            '》': '>',
            
            # 清理词
            '的': '',
            '和': 'and',
            '与': 'and',
            '或': 'or',
            '在': 'in',
            '是': 'is',
            '有': 'has',
            '等': '',
            '中': '',
            '了': '',
            '着': '',
            '过': '',
        }
        
        # 转换提示词
        # 先尝试完整匹配短语（长的先匹配）
        remaining = prompt
        for cn, en in sorted(keyword_map.items(), key=lambda x: -len(x[0])):
            if cn in remaining:
                remaining = remaining.replace(cn, f' {en} ')
        
        # 清理多余空格和重复词
        words = remaining.split()
        cleaned_words = []
        prev_word = None
        for word in words:
            word = word.strip()
            if word and word != prev_word:  # 去重
                cleaned_words.append(word)
                prev_word = word
        
        result = ' '.join(cleaned_words)
        
        # 如果转换后太短，可能是未识别的中文，使用原始提示词的拼音风格描述
        if len(result) < 10 and any('\u4e00' <= c <= '\u9fff' for c in prompt):
            # 生成一个通用的英文描述
            result = self._generate_generic_english_prompt(prompt)
        
        logger.debug(f"转换: {prompt[:40]}... -> {result[:60]}...")
        return result
    
    def _generate_generic_english_prompt(self, prompt: str) -> str:
        """为无法直接翻译的中文生成通用英文描述"""
        # 检测提示词类型
        if any(kw in prompt for kw in ['对比', ' versus ', ' vs ', '左边', '右边', '左侧', '右侧']):
            return 'side-by-side comparison, split screen, two panels showing contrast'
        elif any(kw in prompt for kw in ['界面', '屏幕', 'UI']):
            return 'user interface design, software screen, digital display'
        elif any(kw in prompt for kw in ['流程', '工作流', 'pipeline']):
            return 'workflow diagram, process flow, automated pipeline visualization'
        elif any(kw in prompt for kw in ['架构', '结构', '图']):
            return 'system architecture diagram, technical structure, blueprint style'
        elif any(kw in prompt for kw in ['AI', '智能', '模型']):
            return 'AI technology concept, intelligent system, neural network visualization'
        else:
            return 'conceptual illustration, modern design, professional visual'

    def _enhance_image_prompt(self, prompt: str) -> str:
        """增强图片提示词，将中文内容转换为英文避免渲染错乱"""
        # 转换为英文描述
        english_prompt = self._convert_to_english_prompt(prompt)
        
        # 根据内容类型添加风格前缀（英文）
        tech_keywords = ['AI', 'model', 'tech', 'code', 'data', 'algorithm', 'neural', 'artificial intelligence', 'LLM', 'system', 'interface', 'software']
        is_tech = any(kw in english_prompt.lower() for kw in tech_keywords)
        
        if is_tech:
            return f"Tech-style illustration, {english_prompt}, blue color scheme, futuristic, clean design, atmospheric lighting, high quality, 4K, detailed"
        else:
            return f"Beautiful illustration, {english_prompt}, fine details, elegant color palette, professional cover design, high quality, 4K"
    
    def _slugify(self, text: str) -> str:
        """将文本转换为文件名安全格式"""
        text = re.sub(r'[^\w\s-]', '', text).strip().lower()
        text = re.sub(r'[-\s]+', '-', text)
        return text[:50]
    
    def insert_images_to_article(self, content: str, image_map: Dict[str, str]) -> str:
        """将生成的图片插入到文章中"""
        logger.info(f"开始插入图片 (共 {len(image_map)} 张):")
        
        for placeholder, image_path in image_map.items():
            # 使用相对路径
            rel_path = os.path.relpath(image_path, POSTS_DIR)
            image_md = f"![{placeholder}]({rel_path})\n\n"
            
            # 检查占位符是否存在
            if placeholder in content:
                content = content.replace(placeholder, image_md, 1)
                logger.info(f"   已替换: {placeholder[:40]}...")
                logger.info(f"      -> {rel_path}")
            else:
                logger.warning(f"   占位符不存在: {placeholder[:40]}...")
        
        # 清理未替换的配图标记
        remaining = re.findall(r'\[配图[:：]\s*[^\]]+\]', content)
        if remaining:
            logger.info(f"清理 {len(remaining)} 个未替换的配图标记")
            for r in remaining[:3]:  # 只显示前3个
                logger.info(f"   - {r}")
        content = re.sub(r'\[配图[:：]\s*[^\]]+\]\n?\n?', '', content)
        
        return content
    
    def save_article(self, title: str, content: str, source_article: SourceArticle) -> Path:
        """保存文章到 posts 目录"""
        timestamp = datetime.now().strftime("%Y%m%d")
        slug = self._slugify(title)[:40]
        filename = f"{timestamp}_{slug}.md"
        
        # 添加元信息
        header = f"""---
title: {title}
date: {datetime.now().strftime("%Y-%m-%d %H:%M")}
source: {source_article.title}
original_url: {source_article.source_url or 'N/A'}
style: {self.style}
---

"""
        
        full_content = header + content
        
        output_path = POSTS_DIR / filename
        output_path.write_text(full_content, encoding="utf-8")
        logger.info(f"文章已保存: {output_path}")
        
        return output_path
    
    def process(self, article_title: Optional[str] = None, 
                word_count: int = 1500,
                generate_images: bool = True) -> Optional[Path]:
        """主处理流程"""
        
        # 1. 列出所有源文章
        articles = self.list_source_articles()
        if not articles:
            logger.error("没有找到源文章，请将文章放入 articles 目录")
            return None
        
        logger.info(f"发现 {len(articles)} 篇源文章")
        
        # 2. 选择要处理的文章
        if article_title:
            selected = [a for a in articles if article_title.lower() in a.title.lower()]
            if not selected:
                logger.error(f"未找到匹配的文章: {article_title}")
                return None
            source_article = selected[0]
        else:
            # 默认选择第一篇
            source_article = articles[0]
        
        logger.info(f"已选择: {source_article.title}")
        
        # 3. 分析并选择写作角度
        logger.info("正在分析文章...")
        analysis = self.analyze_and_select_angle(source_article)
        
        logger.info("可选写作角度:")
        for i, angle in enumerate(analysis.get("angles", [])[:3], 1):
            logger.info(f"  {i}. {angle.get('title', 'N/A')} (热度: {angle.get('score', 'N/A')})")
            logger.info(f"     切入点: {angle.get('hook', 'N/A')}")
        
        recommendation = analysis.get("recommendation", "")
        if recommendation:
            logger.info(f"⭐ 推荐: {recommendation}")
        
        # 选择最佳角度
        angles = analysis.get("angles", [])
        best_angle = angles[0] if angles else {"title": "技术解读"}
        
        # 4. 生成文章
        logger.info(f"开始创作文章 (风格: {self.style})...")
        article_content = self.generate_article(source_article, best_angle, word_count)
        
        # 5. 提取标题
        title = self._extract_title(article_content) or f"AI 观察 | {source_article.title}"
        
        if len(title) > 20:
            title = title[:20]
        
        # 6. 生成配图
        image_map = {}
        if generate_images and self.jimeng.is_available():
            image_prompts = self.extract_image_prompts(article_content)
            if image_prompts:
                logger.info(f"检测到 {len(image_prompts)} 个配图需求")
                image_map = self.generate_images(image_prompts, title)
        
        # 7. 插入图片
        if image_map:
            article_content = self.insert_images_to_article(article_content, image_map)
        
        # 8. 保存文章
        output_path = self.save_article(title, article_content, source_article)
        
        logger.info("="*60)
        logger.info("🎉 文章创作完成!")
        logger.info(f"📄 标题: {title}")
        logger.info(f"💾 文件: {output_path}")
        logger.info(f"🎨 配图: {len(image_map)} 张")
        logger.info("="*60)
        
        return output_path
    
    def process_existing_post(self, post_path: str) -> Optional[Path]:
        """从已生成的文章文件处理：提取配图标记、生成图片、插入文章
        
        Args:
            post_path: 已生成文章的路径（如 posts/20260202_xxx.md）
            
        Returns:
            处理后的文章路径
        """
        post_file = Path(post_path)
        if not post_file.exists():
            logger.error(f"文章文件不存在: {post_path}")
            return None
        
        # 读取文章内容
        content = post_file.read_text(encoding="utf-8")
        
        # 解析 frontmatter 和正文
        frontmatter = {}
        body = content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                # 解析 frontmatter
                for line in parts[1].strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        frontmatter[key.strip()] = value.strip()
                body = parts[2].strip()
        
        title = frontmatter.get('title', self._extract_title(body) or post_file.stem)
        
        logger.info(f"处理已生成文章: {title}")
        logger.info(f"   文件: {post_file}")
        
        # 检查是否有配图标记
        image_prompts = self.extract_image_prompts(body)
        if not image_prompts:
            logger.warning("文章中没有找到 [配图: xxx] 标记")
            return post_file
        
        logger.info(f"检测到 {len(image_prompts)} 个配图需求:")
        for i, prompt in enumerate(image_prompts, 1):
            logger.info(f"  {i}. {prompt}")
        
        # 生成配图
        image_map = {}
        if self.jimeng.is_available():
            image_map = self.generate_images(image_prompts, title)
        else:
            logger.warning("即梦 API 未配置，跳过图片生成")
        
        # 插入图片到文章
        if image_map:
            logger.info(f"开始插入图片到文章，映射关系:")
            for placeholder, img_path in image_map.items():
                logger.info(f"   {placeholder[:40]}... -> {img_path}")
            
            new_body = self.insert_images_to_article(body, image_map)
            
            # 重新组装文章
            if content.startswith('---') and len(content.split('---', 2)) >= 3:
                new_content = f"---{content.split('---', 2)[1]}---\n\n{new_body}"
            else:
                new_content = new_body
            
            # 保存回原文件
            post_file.write_text(new_content, encoding="utf-8")
            logger.info(f"图片已插入并保存: {post_file}")
            
            # 验证图片文件是否存在
            logger.info(f"验证图片文件:")
            for img_path in image_map.values():
                exists = os.path.exists(img_path)
                size = os.path.getsize(img_path) if exists else 0
                status = "✅" if exists else "❌"
                logger.info(f"   {status} {img_path} ({size/1024:.1f} KB)" if exists else f"   {status} {img_path} (不存在)")
        else:
            logger.warning("没有生成图片，文章保持不变")
        
        logger.info("="*60)
        logger.info("🎉 文章配图完成!")
        logger.info(f"📄 标题: {title}")
        logger.info(f"💾 文件: {post_file}")
        logger.info(f"🎨 配图: {len(image_map)} 张")
        logger.info("="*60)
        
        return post_file


def main():
    parser = argparse.ArgumentParser(
        description="公众号协作助手 - 基于 Kimi 2.5 API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python wechat_assistant.py                          # 自动生成文章
  python wechat_assistant.py --article "Step 3.5"     # 指定源文章
  python wechat_assistant.py --style "故事"            # 选择写作风格
  python wechat_assistant.py --words 2000             # 指定字数
  python wechat_assistant.py --no-image               # 不生成配图
  python wechat_assistant.py --from-post posts/xxx.md # 为已有文章生成配图

环境变量:
  KIMI_API_KEY    Kimi API Key (必需)
  JIMENG_TOKEN    即梦 session token (可选)
        """
    )
    
    parser.add_argument("--article", "-a", help="指定源文章标题关键词")
    parser.add_argument("--from-post", "-p", help="从已生成的文章文件处理（生成配图），如 posts/xxx.md")
    parser.add_argument("--style", "-s", 
                        choices=list(WRITING_STYLES.keys()),
                        default="犀利",
                        help="写作风格 (默认: 犀利)")
    parser.add_argument("--words", "-w", type=int, default=1500,
                        help="目标字数 (默认: 1500)")
    parser.add_argument("--no-image", action="store_true",
                        help="不生成配图")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出所有可用的源文章")
    
    args = parser.parse_args()
    
    assistant = WeChatArticleAssistant(style=args.style)
    
    # 列出文章（不需要 API Key）
    if args.list:
        assistant = WeChatArticleAssistant(style=args.style)
        articles = assistant.list_source_articles()
        logger.info(f"共 {len(articles)} 篇源文章:")
        for i, a in enumerate(articles, 1):
            logger.info(f"  {i}. {a.title}")
            logger.info(f"     文件: {a.file_path.name}")
        return
    
    # 从已有文章处理（仅生成配图，不需要 KIMI_API_KEY）
    if args.from_post:
        result = assistant.process_existing_post(args.from_post)
        if result:
            logger.info(f"文章已更新: {result}")
        else:
            sys.exit(1)
        return
    
    # 检查必要的环境变量
    if not os.environ.get("KIMI_API_KEY", ""):
        logger.error("请设置 KIMI_API_KEY 环境变量")
        logger.error("   例如: export KIMI_API_KEY='your-api-key'")
        sys.exit(1)
    
    # 执行创作流程
    try:
        result = assistant.process(
            article_title=args.article,
            word_count=args.words,
            generate_images=not args.no_image
        )
        
        if result:
            logger.info(f"下一步: 检查 {result} 并发布到公众号")
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("已取消")
        sys.exit(0)
    except Exception as e:
        logger.error(f"错误: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
