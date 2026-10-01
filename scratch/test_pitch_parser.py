"""
Comprehensive Pitch & Intonation Parser for O-Voice Studio.
"""
import re
from typing import List, Tuple, NamedTuple, Optional

class Segment(NamedTuple):
    text: str
    pause_after: float
    speed: float
    pitch: float
    is_sentence_end: bool = True

SEMANTIC_PITCH_MAP = {
    "high": 1.12,
    "up": 1.12,
    "elevate": 1.12,
    "higher": 1.20,
    "excited": 1.20,
    "peak": 1.22,
    "low": 0.88,
    "down": 0.88,
    "deep": 0.84,
    "lower": 0.82,
    "somber": 0.82,
    "whisper": 0.78,
    "hush": 0.78,
    "aside": 0.85,
    "rise": 1.10,
    "question": 1.10,
    "drop": 0.90,
    "fall": 0.90,
    "normal": 1.0,
    "neutral": 1.0,
    "reset": 1.0,
}

SEMANTIC_SPEED_MAP = {
    "fast": 0.25,
    "faster": 0.40,
    "slow": -0.20,
    "slower": -0.35,
    "normal": 0.0,
    "rush": 0.35,
    "deliberate": -0.15,
}

def resolve_pitch_value(raw: str, base_pitch: float = 1.0) -> float:
    raw_str = raw.strip().lower()
    if raw_str in SEMANTIC_PITCH_MAP:
        return round(max(0.5, min(1.5, base_pitch * SEMANTIC_PITCH_MAP[raw_str])), 3)
    if raw_str.endswith('%'):
        try:
            pct_val = float(raw_str[:-1])
            return round(max(0.5, min(1.5, base_pitch * (1.0 + pct_val / 100.0))), 3)
        except ValueError:
            pass
    if raw_str.startswith('+') or raw_str.startswith('-'):
        try:
            delta = float(raw_str)
            return round(max(0.5, min(1.5, base_pitch + delta)), 3)
        except ValueError:
            pass
    try:
        val = float(raw_str)
        return round(max(0.5, min(1.5, val)), 3)
    except ValueError:
        return round(base_pitch, 3)

def resolve_speed_value(raw: str, base_speed: float = 0.0) -> float:
    raw_str = raw.strip().lower()
    if raw_str in SEMANTIC_SPEED_MAP:
        return round(max(-1.0, min(1.0, base_speed + SEMANTIC_SPEED_MAP[raw_str])), 3)
    if raw_str.endswith('%'):
        try:
            pct_val = float(raw_str[:-1])
            return round(max(-1.0, min(1.0, base_speed + (pct_val / 100.0))), 3)
        except ValueError:
            pass
    try:
        val = float(raw_str)
        return round(max(-1.0, min(1.0, val)), 3)
    except ValueError:
        return round(base_speed, 3)

def clean_text_segment(text: str, is_sentence_end: bool = True) -> str:
    t = text.strip()
    if not t:
        return ""
    t = re.sub(r'\s*—\s*', ' — ', t)
    t = re.sub(r'\s*--\s*', ' — ', t)
    t = re.sub(r'\.{2,}', '...', t)
    if is_sentence_end:
        # If text ends with punctuation (or punctuation followed by quote/parenthesis), don't append period
        if not re.search(r'[.!?…][)"]?$', t):
            t += '.'
    return t

# Master pattern for prosody tags & pause tags using named groups throughout
TAG_REGEX = re.compile(
    r'(?P<pause>\[(?:pause|break)[:\s]*(?P<pause_num>[\d.]*)s?\]|\((?:pause|break)[:\s]*(?P<pause_num_paren>[\d.]*)s?\)|\[beat\]|<break\s+time=["\']?(?P<pause_num_xml>[\d.]+)(?P<pause_unit>m?s)["\']?\s*/?>)'
    r'|'
    r'(?P<pitch_tag>\[pitch(?::|\s*=)\s*(?P<pitch_arg>[^\]]+)\](?P<pitch_content>.*?)\[/pitch\])'
    r'|'
    r'(?P<speed_tag>\[speed(?::|\s*=)\s*(?P<speed_arg>[^\]]+)\](?P<speed_content>.*?)\[/speed\])'
    r'|'
    r'(?P<named_pitch_tag>\[(?P<named_tag>high|higher|excited|low|lower|deep|whisper|rise|drop)\](?P<named_content>.*?)\[/(?P=named_tag)\])'
    r'|'
    r'(?P<ssml_prosody><prosody(?:\s+pitch=["\']?(?P<ssml_pitch_val>[^"\'>]+)["\']?)?(?:\s+rate=["\']?(?P<ssml_rate_val>[^"\'>]+)["\']?)?\s*>(?P<prosody_content>.*?)</prosody>)'
    r'|'
    r'(?P<ssml_pitch><pitch(?:\s+val(?:ue)?=["\']?(?P<xml_pitch_val>[^"\'>]+)["\']?)?\s*>(?P<xml_pitch_content>.*?)</pitch>)',
    re.IGNORECASE | re.DOTALL
)

def parse_paragraph_intonation(
    para: str,
    default_pause: float,
    base_speed: float = 0.0,
    base_pitch: float = 1.0,
    smart_intonation: bool = True,
    is_last_paragraph: bool = False
) -> List[Segment]:
    """
    Parses a single paragraph into segments with per-word or per-sentence pitch & speed.
    """
    segments: List[Segment] = []
    
    # Check if there are any explicit tags in this paragraph
    matches = list(TAG_REGEX.finditer(para))
    
    if not matches:
        # No explicit tags inside paragraph.
        # Check if smart_intonation should split on sentence punctuation (? / ! / ...)
        if smart_intonation and re.search(r'[?!]', para):
            # Split into sentences to give questions rising pitch and exclamations energy lift
            sentence_parts = re.split(r'([.!?…]+(?:\s+|$))', para)
            i = 0
            while i < len(sentence_parts):
                sent_text = sentence_parts[i]
                punct = sentence_parts[i+1] if i + 1 < len(sentence_parts) else ""
                i += 2
                
                combined = (sent_text + punct).strip()
                if not combined:
                    continue
                
                # Determine smart pitch
                seg_pitch = base_pitch
                if combined.endswith('?'):
                    seg_pitch = round(min(1.5, base_pitch * 1.07), 3)  # Inquiry / question rise
                elif combined.endswith('!'):
                    seg_pitch = round(min(1.5, base_pitch * 1.08), 3)  # Exclamation / excitement
                elif combined.startswith('(') and combined.endswith(')'):
                    seg_pitch = round(max(0.5, base_pitch * 0.92), 3)  # Parenthetical / aside
                
                is_para_end = (i >= len(sentence_parts))
                pause_after = (0.0 if is_last_paragraph else default_pause) if is_para_end else 0.32
                
                clean_s = clean_text_segment(combined, is_sentence_end=True)
                if clean_s:
                    segments.append(Segment(clean_s, pause_after, base_speed, seg_pitch, is_sentence_end=True))
            return segments
        
        # Plain paragraph without tags or ?/!
        clean_p = clean_text_segment(para, is_sentence_end=True)
        if clean_p:
            pause_after = 0.0 if is_last_paragraph else default_pause
            segments.append(Segment(clean_p, pause_after, base_speed, base_pitch, is_sentence_end=True))
        return segments

    def add_plain_block(raw_text: str):
        if not raw_text.strip():
            return
        # If the plain block has multiple sentences, split them so sentence pauses and smart intonation apply
        # Match sentence end: [.!?…]+ followed by whitespace or end of string
        parts = re.split(r'([.!?…]+(?:\s+|$))', raw_text)
        i = 0
        while i < len(parts):
            txt = parts[i]
            punct = parts[i+1] if i + 1 < len(parts) else ""
            i += 2
            combined = (txt + punct).strip()
            if not combined:
                continue
            
            # Smart pitch for punctuation
            p = base_pitch
            if smart_intonation:
                if combined.endswith('?'):
                    p = round(min(1.5, base_pitch * 1.07), 3)
                elif combined.endswith('!'):
                    p = round(min(1.5, base_pitch * 1.08), 3)
                elif combined.startswith('(') and combined.endswith(')'):
                    p = round(max(0.5, base_pitch * 0.92), 3)
            
            raw_tokens.append(("plain", combined, base_speed, p, 0.0))

    last_end = 0
    raw_tokens = [] # (type, text, speed, pitch, pause_duration)

    for match in matches:
        start, end = match.span()
        if start > last_end:
            interim = para[last_end:start]
            add_plain_block(interim)
        
        m_dict = match.groupdict()

        # Check if immediate next character is trailing punctuation (e.g. [/pitch]. or [/pitch],)
        trailing_punct_match = re.match(r'^([.!?…]+|[,;:])(?:\s+|$)', para[end:])
        trailing_punct = ""
        if trailing_punct_match and not m_dict.get("pause"):
            trailing_punct = trailing_punct_match.group(1)
            end += trailing_punct_match.end()

        if m_dict.get("pause"):
            full_tag = match.group(0).lower()
            dur_val = m_dict.get("pause_num") or m_dict.get("pause_num_paren") or m_dict.get("pause_num_xml")
            unit = m_dict.get("pause_unit") or 's'
            if dur_val:
                try:
                    p_sec = float(dur_val)
                    if unit == 'ms':
                        p_sec /= 1000.0
                except ValueError:
                    p_sec = 0.6
            elif 'beat' in full_tag:
                p_sec = 0.5
            else:
                p_sec = 0.8
            raw_tokens.append(("pause", "", base_speed, base_pitch, p_sec))
            
        elif m_dict.get("pitch_tag"):
            pitch_arg = m_dict.get("pitch_arg") or "1.0"
            content = (m_dict.get("pitch_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(pitch_arg, base_pitch)
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))
            
        elif m_dict.get("speed_tag"):
            speed_arg = m_dict.get("speed_arg") or "0.0"
            content = (m_dict.get("speed_content") or "") + trailing_punct
            target_speed = resolve_speed_value(speed_arg, base_speed)
            raw_tokens.append(("tagged", content, target_speed, base_pitch, 0.0))
            
        elif m_dict.get("named_pitch_tag"):
            tag_name = m_dict.get("named_tag") or "normal"
            content = (m_dict.get("named_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(tag_name, base_pitch)
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))
            
        elif m_dict.get("ssml_prosody"):
            p_arg = m_dict.get("ssml_pitch_val")
            r_arg = m_dict.get("ssml_rate_val")
            content = (m_dict.get("prosody_content") or "") + trailing_punct
            seg_p = resolve_pitch_value(p_arg, base_pitch) if p_arg else base_pitch
            seg_s = resolve_speed_value(r_arg, base_speed) if r_arg else base_speed
            raw_tokens.append(("tagged", content, seg_s, seg_p, 0.0))
            
        elif m_dict.get("ssml_pitch"):
            val_arg = m_dict.get("xml_pitch_val")
            content = (m_dict.get("xml_pitch_content") or "") + trailing_punct
            target_pitch = resolve_pitch_value(val_arg, base_pitch) if val_arg else base_pitch
            raw_tokens.append(("tagged", content, base_speed, target_pitch, 0.0))
            
        last_end = end

    if last_end < len(para):
        rem = para[last_end:]
        add_plain_block(rem)

    # Now turn tokens into seamless Segments:
    # A token followed by another mid-sentence token has pause_after = 0.0
    # A token with a pause token immediately following gets that pause duration
    # A token ending a sentence gets sentence_pause (0.3s)
    # The last token in the paragraph gets default_pause (or 0 if last para)
    
    active_tokens: List[Tuple[str, float, float, float]] = [] # (text, speed, pitch, pending_pause)
    
    for t_type, t_text, t_speed, t_pitch, t_pause in raw_tokens:
        if t_type == "pause":
            if active_tokens:
                txt, spd, pit, p_pause = active_tokens[-1]
                active_tokens[-1] = (txt, spd, pit, p_pause + t_pause)
        else:
            txt = t_text.strip()
            if txt:
                active_tokens.append((txt, t_speed, t_pitch, 0.0))

    for idx, (txt, spd, pit, explicit_pause) in enumerate(active_tokens):
        is_last_token = (idx == len(active_tokens) - 1)
        ends_sentence = bool(re.search(r'[.!?…]$', txt))
        
        # Calculate pause_after
        if explicit_pause > 0:
            pause_after = explicit_pause
        elif is_last_token:
            pause_after = 0.0 if is_last_paragraph else default_pause
        elif ends_sentence:
            pause_after = 0.30
        else:
            # Mid-sentence word or clause: zero pause so speech flows seamlessly
            pause_after = 0.0
            
        clean_text = clean_text_segment(txt, is_sentence_end=ends_sentence)
        if clean_text:
            segments.append(Segment(clean_text, pause_after, spd, pit, is_sentence_end=ends_sentence))
            
    return segments

def parse_script_into_segments(
    text: str,
    default_paragraph_pause: float = 0.8,
    base_speed: float = 0.0,
    base_pitch: float = 1.0,
    smart_intonation: bool = True
) -> List[Segment]:
    if not text or not text.strip():
        return []
    
    norm_text = text.replace('\r\n', '\n').strip()
    raw_paragraphs = [p.strip() for p in re.split(r'\n\s*\n', norm_text) if p.strip()]
    
    all_segments: List[Segment] = []
    for p_idx, para in enumerate(raw_paragraphs):
        is_last = (p_idx == len(raw_paragraphs) - 1)
        p_segs = parse_paragraph_intonation(
            para=para,
            default_pause=default_paragraph_pause,
            base_speed=base_speed,
            base_pitch=base_pitch,
            smart_intonation=smart_intonation,
            is_last_paragraph=is_last
        )
        all_segments.extend(p_segs)
        
    return all_segments

# Run additional tests
test_cases = [
    ("The [pitch: +15%]only[/pitch] way forward.", "Mid-sentence single word pitch boost"),
    ("Wait for it... [pause: 1.2s] Boom!", "Explicit pause tag"),
    ("<prosody pitch='+10%' rate='-10%'>Deliberate high pitch</prosody> and normal text.", "SSML prosody"),
    ("Are you sure? Yes, absolutely! (Or maybe not.)", "Smart intonation question, exclamation, and parenthetical"),
]

for script, desc in test_cases:
    print(f"\n--- Test: {desc} ---")
    print(f"Input: {script}")
    parsed = parse_script_into_segments(script, default_paragraph_pause=0.8, base_pitch=1.0, smart_intonation=True)
    for i, s in enumerate(parsed):
        print(f"  [{i+1}] text={s.text!r:35} pause={s.pause_after}s speed={s.speed} pitch={s.pitch} (sentence_end={s.is_sentence_end})")
