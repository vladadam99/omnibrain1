# -*- coding: utf-8 -*-
import re
import time

# This will store per-user (per chat_id) conversation state
user_context = {}

def parse_intent(text):
    text = text.lower()
    # You can expand these patterns for more natural language!
    if "pause" in text or "stop trading" in text:
        return "pause"
    if "resume" in text or "start trading" in text:
        return "resume"
    if "risk" in text or "leverage" in text or "confidence" in text:
        return "risk"
    if "stats" in text or "summary" in text or "report" in text:
        return "summary"
    if "portfolio" in text or "position" in text or "show" in text:
        return "portfolio"
    if "threshold" in text:
        return "threshold"
    if "undo" in text or "revert" in text:
        return "undo"
    if "news" in text:
        return "news"
    if "help" in text:
        return "help"
    if "schedule" in text or ("until" in text and ("stop" in text or "pause" in text)):
        return "schedule"
    # Add more intents as needed!
    return "unknown"

def handle_telegram_message(chat_id, text):
    ctx = user_context.get(chat_id, {})
    intent = ctx.get('intent') or parse_intent(text)
    reply = ""
    # Step 2+ of conversation
    if ctx.get('awaiting'):
        if ctx['awaiting'] == "risk_type":
            if "all" in text or "preset" in text:
                reply = "Which risk preset, Vlad? 😃 (aggressive, normal, conservative)"
                ctx['awaiting'] = "risk_preset"
            elif "leverage" in text:
                reply = "What leverage would you like, Vlad? 😃 (e.g. 5, 10, 20)"
                ctx['awaiting'] = "risk_leverage"
            elif "position" in text or "size" in text:
                reply = "What max position size (e.g. 0.1 = 10%), Vlad? 😃"
                ctx['awaiting'] = "risk_pos_size"
            elif "confidence" in text:
                reply = "What should the new confidence threshold be, Vlad? 😃 (e.g. 0.8)"
                ctx['awaiting'] = "risk_conf"
            else:
                reply = "Not sure what you mean, Vlad 😃. Choose: leverage, position size, confidence, or preset."
        elif ctx['awaiting'] == "risk_leverage":
            try:
                lev = int(re.findall(r"\d+", text)[0])
                # set_leverage(lev) ...
                reply = f"Leverage set to {lev}x, Vlad! 😃"
                ctx.clear()
            except:
                reply = "Sorry Vlad 😃, I couldn't parse that leverage. Try a number (e.g. 10)."
        elif ctx['awaiting'] == "risk_pos_size":
            try:
                sz = float(re.findall(r"[\d\.]+", text)[0])
                # set_max_pos_size(sz) ...
                reply = f"Max position size set to {sz:.2f}, Vlad! 😃"
                ctx.clear()
            except:
                reply = "Sorry Vlad 😃, please give a percent like 0.2 for 20%."
        elif ctx['awaiting'] == "risk_conf":
            try:
                conf = float(re.findall(r"[\d\.]+", text)[0])
                # set_confidence_threshold(conf) ...
                reply = f"Confidence threshold set to {conf:.2f}, Vlad! 😃"
                ctx.clear()
            except:
                reply = "Sorry Vlad 😃, try a number like 0.85."
        elif ctx['awaiting'] == "risk_preset":
            preset = text.strip().lower()
            if preset in ("aggressive", "normal", "conservative"):
                # set_risk_preset(preset) ...
                reply = f"Risk preset changed to {preset}, Vlad! 😃"
                ctx.clear()
            else:
                reply = "Please type aggressive, normal, or conservative, Vlad 😃."
        elif ctx['awaiting'] == "pause_time":
            m = re.search(r"(\d+)\s*h", text)
            if m:
                hours = int(m.group(1))
                pause_until = time.time() + hours * 3600
                reply = f"Trading paused for {hours} hours, Vlad! 😃"
                ctx.clear()
            elif "until" in text:
                # Parse time string, set pause_until...
                reply = f"Trading paused until your specified time, Vlad! 😃"
                ctx.clear()
            else:
                reply = "Please specify pause duration, Vlad 😃 (e.g. 1h, until 2pm)."
        elif ctx['awaiting'] == "portfolio_action":
            if "close" in text and "all" in text:
                # close_all_positions()
                reply = "Closed all positions for you, Vlad! 😃"
                ctx.clear()
            elif "close" in text:
                # Try to extract symbol
                m = re.search(r"close\s+([A-Z]+USDT)", text)
                symbol = m.group(1) if m else None
                if symbol:
                    # close_position(symbol)
                    reply = f"Closed {symbol} for you, Vlad! 😃"
                    ctx.clear()
                else:
                    reply = "Please specify which position to close, Vlad 😃 (e.g. close BTCUSDT)."
            else:
                reply = "Let me know if you want to close anything, Vlad 😃."
        elif ctx['awaiting'] == "threshold_agent":
            agent = text.strip().lower()
            if agent == "list":
                # list_thresholds()
                reply = "Here are your current agent thresholds, Vlad! 😃\n[agent: threshold ...]"
                ctx.clear()
            else:
                reply = f"What threshold for {agent}, Vlad? 😃 (e.g. 0.85)"
                ctx['awaiting'] = "set_threshold_value"
                ctx['agent'] = agent
        elif ctx['awaiting'] == "set_threshold_value":
            try:
                conf = float(re.findall(r"[\d\.]+", text)[0])
                agent = ctx.get('agent', '')
                # set_agent_threshold(agent, conf)
                reply = f"Threshold for {agent} set to {conf:.2f}, Vlad! 😃"
                ctx.clear()
            except:
                reply = "Sorry Vlad 😃, try a number like 0.85."
        elif ctx['awaiting'] == "undo_what":
            reply = "Undoing your last change, Vlad! 😃"
            ctx.clear()
        # Add more handlers for other multi-step flows as needed!
    else:
        if intent == "pause":
            reply = "How long should I pause trading, Vlad? 😃 (e.g. 1h, until 2pm)"
            ctx['awaiting'] = "pause_time"
        elif intent == "resume":
            # resume_trading() ...
            reply = "Trading resumed, Vlad! 😃"
        elif intent == "risk":
            reply = (
                "What would you like to change about your risk, Vlad? 😃\n"
                "- Position size\n- Leverage\n- Confidence threshold\n- Preset (all)\n(Type your choice)"
            )
            ctx['awaiting'] = "risk_type"
        elif intent == "portfolio":
            # show_portfolio() ...
            reply = "Here's your portfolio, Vlad! 😃\n[positions...]\nWant to close any? (yes/no or symbol)"
            ctx['awaiting'] = "portfolio_action"
        elif intent == "summary":
            # show_summary() ...
            reply = "Here's your summary, Vlad! 😃\n[PnL, trades, best/worst]"
        elif intent == "threshold":
            reply = (
                "Which agent's threshold, Vlad? 😃 (e.g. macd, 'all', or 'list' to see current values)"
            )
            ctx['awaiting'] = "threshold_agent"
        elif intent == "undo":
            reply = "What would you like to undo, Vlad? 😃 (last risk change, last trade, etc)"
            ctx['awaiting'] = "undo_what"
        elif intent == "news":
            # get_market_news() ...
            reply = "Fetching latest crypto news for you, Vlad! 😃"
        elif intent == "help":
            reply = (
                "Hi Vlad! 😃 You can say things like:\n"
                "- 'Pause trading until 2pm'\n- 'Change my risk'\n- 'Show summary'\n- 'Undo last change'\n"
                "- 'Set confidence to 0.8'\n- 'Trade only BTCUSDT'\n- 'Close all positions'\n"
                "- 'List thresholds'"
            )
        elif intent == "schedule":
            reply = "When should I stop or start trading, Vlad? 😃 (e.g. stop until 2am, trade only between 8am-4pm)"
            ctx['awaiting'] = "pause_time"
        else:
            reply = (
                "Sorry Vlad 😃, I didn't get that! You can ask to pause/resume trading, adjust risk, "
                "see your portfolio, and much more. Type 'help' for ideas!"
            )
    user_context[chat_id] = ctx
    return reply