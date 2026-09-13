import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone

import nextcord
from nextcord.ext import commands, tasks

# --- Константы ---
DATA_PATH = "data/giveaways.json"

GIVEAWAY_CHANNEL_ID = 846820668544909343
EXCLUDED_CHANNEL_ID = 850588016862822430
DOUBLE_ACTIVITY_CHANNEL_ID = 1539280832651468801
MIN_MESSAGES = 100
OWNER_ID = 942776739870933003

SCAN_PAUSE_BETWEEN_CHANNELS = 0.8
SCAN_PAGE_SIZE = 100
MAX_RETRIES_ON_429 = 3

# --- Эмодзи (строки) ---
EMOJI_STAR = "<:solar_starringbroken:1543314841794514984>"
EMOJI_ADD = "<:add:1543377077527650374>"
EMOJI_HISTORY = "<:history:1543377106157707335>"
EMOJI_CHECK = "<:check:1543374191980580925>"
EMOJI_CROSS = "<:cross:1543374204353650799>"
EMOJI_CROWN = "<:solar_crownbroken:1543314667214995456>"
EMOJI_WARN = "<:warn:1536478044552695938>"
EMOJI_CLIPBOARD = "<:clipboard:1536478319824871515>"
EMOJI_INFO = "<:info:1536425715124146290>"

# --- Эмодзи для кнопок ---
PE_ADD = nextcord.PartialEmoji.from_str(EMOJI_ADD)
PE_HISTORY = nextcord.PartialEmoji.from_str(EMOJI_HISTORY)

# --- JSON утилиты ---
def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- Парсер времени ---
_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "сек": 1, "секунд": 1, "секунды": 1, "секунда": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "мин": 60, "минут": 60, "минуты": 60, "минута": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "д": 86400, "день": 86400, "дня": 86400, "дней": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    "н": 604800, "нед": 604800, "неделя": 604800, "недели": 604800, "недель": 604800,
}

def parse_duration(text: str) -> int | None:
    text = text.strip().lower()
    if not text:
        return None
    total = 0
    found = False
    pattern = re.compile(r"(\d+)\s*([a-zа-я]+)")
    for num, unit in pattern.findall(text):
        base = unit.rstrip("аеиоуыэюя")
        mult = _UNITS.get(unit) or _UNITS.get(base) or _UNITS.get(base + "а") or _UNITS.get(base + "ов")
        if mult:
            total += int(num) * mult
            found = True
    return total if found else None

# --- Эмбед розыгрыша ---
def build_giveaway_embed(author, description, prize, winners, end_ts, participants, banner_url):
    prize_line = f"А приз — **{prize}**"
    if winners > 1:
        prize_line += f" и разделят его: **{winners}**"
    prize_line += "."

    embed = nextcord.Embed(
        title=f"{EMOJI_STAR} / Розыгрыш.",
        description=(
            f"{author.mention} инициирует розыгрыш, в котором победить может каждый.\n"
            f"{description}\n"
            f"{prize_line}\n\n"
            f"Успевайте поучаствовать, ведь он подойдёт к концу через <t:{end_ts}:R>\n"
            f"Участников: **{participants}**"
        ),
    )
    if banner_url:
        embed.set_image(url=banner_url)
    embed.set_footer(text="Нажми кнопку ниже, чтобы участвовать")
    return embed

# --- Persistent: участие ---
class JoinView(nextcord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id

    @nextcord.ui.button(
        label="Участвовать",
        emoji=PE_ADD,
        style=nextcord.ButtonStyle.green,
        custom_id="join:placeholder",
    )
    async def join_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        gid = button.custom_id.split(":", 1)[1]
        giveaways = load_json(DATA_PATH, {})
        g = giveaways.get(gid)
        if not g:
            await interaction.response.send_message(f"{EMOJI_CROSS} Розыгрыш не найден.", ephemeral=True)
            return
        if g.get("finished"):
            await interaction.response.send_message(f"{EMOJI_CROSS} Розыгрыш уже завершён.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if user_id in g["participants"]:
            await interaction.response.send_message(f"{EMOJI_CROSS} Ты уже участвуешь!", ephemeral=True)
            return

        g["participants"].append(user_id)
        save_json(DATA_PATH, giveaways)

        try:
            channel = interaction.client.get_channel(g["channel_id"])
            msg = await channel.fetch_message(g["message_id"])
            embed = msg.embeds[0]
            embed.description = "\n".join(
                f"Участников: **{len(g['participants'])}**" if line.startswith("Участников:") else line
                for line in embed.description.split("\n")
            )
            await msg.edit(embed=embed)
        except Exception:
            pass

        await interaction.response.send_message(f"{EMOJI_CHECK} Ты записан в розыгрыш!", ephemeral=True)

# --- Persistent: реролл ---
class RerollView(nextcord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)

    @nextcord.ui.button(
        label="Реролл",
        emoji=PE_HISTORY,
        style=nextcord.ButtonStyle.red,
        custom_id="reroll:placeholder",
    )
    async def reroll(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(f"{EMOJI_CROSS} Нет прав.", ephemeral=True)
            return

        gid = button.custom_id.split(":", 1)[1]
        giveaways = load_json(DATA_PATH, {})
        g = giveaways.get(gid)
        if not g:
            await interaction.response.send_message(f"{EMOJI_CROSS} Розыгрыш не найден.", ephemeral=True)
            return

        pool = [p for p in g["participants"] if p not in g.get("past_winners", [])]
        if not pool:
            await interaction.response.send_message(f"{EMOJI_CROSS} Больше нет участников для реролла.", ephemeral=True)
            return

        winner_id = random.choice(pool)
        g.setdefault("past_winners", []).append(winner_id)
        save_json(DATA_PATH, giveaways)

        member = interaction.guild.get_member(int(winner_id)) if interaction.guild else None
        mention = member.mention if member else f"<@{winner_id}>"

        await interaction.response.send_message(
            f"{EMOJI_HISTORY} Новый победитель: {mention}",
            reference=interaction.message,
        )

# --- Cog ---
class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._pending = None
        self.check_loop.start()

    def cog_unload(self):
        self.check_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        giveaways = load_json(DATA_PATH, {})
        for gid, g in giveaways.items():
            if g.get("finished"):
                continue
            self.bot.add_view(JoinView(gid))
            self.bot.add_view(RerollView(gid))

    # ---------- Сканер активности ----------
    async def scan_activity(
        self,
        guild: nextcord.Guild,
        user_id: int,
        progress_message: nextcord.Message | None = None,
        progress_prefix: str = f"{EMOJI_HISTORY} Идёт подсчёт",
    ) -> int:
        if guild is None:
            return 0

        total = 0
        scanned = 0
        channels = [ch for ch in guild.text_channels if ch.id != EXCLUDED_CHANNEL_ID]

        for ch in channels:
            scanned += 1
            if progress_message is not None and scanned % 5 == 0:
                try:
                    await progress_message.edit(
                        content=f"{progress_prefix}… ({scanned}/{len(channels)} каналов)"
                    )
                except Exception:
                    pass

            weight = 2 if ch.id == DOUBLE_ACTIVITY_CHANNEL_ID else 1

            try:
                last_id = None
                while True:
                    kwargs = {"limit": SCAN_PAGE_SIZE}
                    if last_id is not None:
                        kwargs["before"] = nextcord.Object(id=last_id)
                    got = 0
                    async for msg in ch.history(**kwargs):
                        got += 1
                        last_id = msg.id
                        if msg.author.id == user_id and not msg.author.bot:
                            total += weight
                    if got < SCAN_PAGE_SIZE:
                        break
                    await asyncio.sleep(SCAN_PAUSE_BETWEEN_CHANNELS)
            except nextcord.Forbidden:
                continue
            except nextcord.HTTPException as e:
                if e.status == 429:
                    retry = getattr(e, "retry_after", None) or 5
                    await asyncio.sleep(retry)
                    continue
                continue

            await asyncio.sleep(SCAN_PAUSE_BETWEEN_CHANNELS)

        return total

    # ---------- Команда проверки активности ----------
    @nextcord.slash_command(name="check_activity", description="Проверить активность участника")
    async def check_activity(
        self,
        interaction: nextcord.Interaction,
        user: nextcord.Member = nextcord.SlashOption(
            name="user",
            description="Участник, чью активность нужно проверить",
            required=True,
        ),
    ):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(f"{EMOJI_CROSS} Недостаточно прав.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        progress = await interaction.followup.send(
            f"{EMOJI_HISTORY} Идёт подсчёт активности для {user.mention}…", wait=True, ephemeral=True
        )
        count = await self.scan_activity(interaction.guild, user.id, progress)
        await progress.edit(
            content=f"{EMOJI_CHECK} Активность {user.mention}: **{count}** "
                    f"(с учётом x2 в <#{DOUBLE_ACTIVITY_CHANNEL_ID}>)"
        )

    # ---------- Визард ----------
    def _check(self, user_id: int, channel_id: int):
        def check(m: nextcord.Message):
            return m.author.id == user_id and m.channel.id == channel_id
        return check

    async def _ask(self, interaction, prompt, user_id, channel_id):
        await interaction.channel.send(prompt)
        try:
            msg = await self.bot.wait_for("message", check=self._check(user_id, channel_id), timeout=600)
        except TimeoutError:
            await interaction.channel.send(f"{EMOJI_CROSS} Время вышло, отмена.")
            return None
        content = msg.content.strip()
        if content.lower() == "cancel":
            await interaction.channel.send(f"{EMOJI_CROSS} Создание розыгрыша отменено.")
            return "cancel"
        return content

    @nextcord.slash_command(name="create_giveaway", description="Создать розыгрыш")
    async def create_giveaway(self, interaction: nextcord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(f"{EMOJI_CROSS} Недостаточно прав.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{EMOJI_STAR} Запускаю мастер создания розыгрыша…\n"
            f"{EMOJI_INFO} На любом шаге напишите `cancel`, чтобы отменить."
        )
        await self._run_wizard(interaction)

    async def _run_wizard(self, interaction: nextcord.Interaction):
        user_id = interaction.user.id
        channel_id = interaction.channel.id

        # 1. Время
        while True:
            time_raw = await self._ask(interaction, f"{EMOJI_HISTORY} Введите время (например, `36h` или `36 часов`):", user_id, channel_id)
            if time_raw in (None, "cancel"):
                return
            seconds = parse_duration(time_raw)
            if seconds and seconds > 0:
                break
            await interaction.channel.send(f"{EMOJI_CROSS} Не понял формат. Попробуйте снова, например: `36h`, `2d`, `30 минут`.")

        # 2. Описание
        description = await self._ask(interaction, f"{EMOJI_CLIPBOARD} Введите описание розыгрыша (условия и т.д.):", user_id, channel_id)
        if description in (None, "cancel"):
            return

        # 3. Кол-во мест
        while True:
            winners_raw = await self._ask(interaction, f"{EMOJI_CROWN} Укажите количество призовых мест (например, `1`):", user_id, channel_id)
            if winners_raw in (None, "cancel"):
                return
            try:
                winners = int(winners_raw)
                if winners > 0:
                    break
            except ValueError:
                pass
            await interaction.channel.send(f"{EMOJI_CROSS} Нужно целое положительное число.")

        # 4. Приз
        prize = await self._ask(interaction, f"{EMOJI_ADD} Укажите приз:", user_id, channel_id)
        if prize in (None, "cancel"):
            return

        # 5. Баннер
        await interaction.channel.send(f"{EMOJI_INFO} Прикрепите баннер, напишите `skip` или `cancel` для отмены.")
        try:
            banner_msg = await self.bot.wait_for("message", check=self._check(user_id, channel_id), timeout=600)
        except TimeoutError:
            await interaction.channel.send(f"{EMOJI_CROSS} Время вышло, отмена.")
            return
        banner_content = banner_msg.content.strip()
        if banner_content.lower() == "cancel":
            await interaction.channel.send(f"{EMOJI_CROSS} Создание розыгрыша отменено.")
            return
        banner_url = None
        if banner_content.lower() != "skip" and banner_msg.attachments:
            banner_url = banner_msg.attachments[0].url

        end_ts = int((datetime.now(timezone.utc) + timedelta(seconds=seconds)).timestamp())
        embed = build_giveaway_embed(interaction.user, description, prize, winners, end_ts, 0, banner_url)

        await interaction.channel.send(
            "Вот так будет выглядеть розыгрыш.\n"
            f"Напишите **ok** для подтверждения, **edit** — чтобы заполнить заново, **cancel** — чтобы отменить.",
            embed=embed,
        )

        self._pending = {
            "description": description,
            "prize": prize,
            "winners": winners,
            "seconds": seconds,
            "end_ts": end_ts,
            "banner_url": banner_url,
            "user_id": user_id,
            "channel_id": channel_id,
        }

        while True:
            try:
                decision = await self.bot.wait_for("message", check=self._check(user_id, channel_id), timeout=600)
            except TimeoutError:
                await interaction.channel.send(f"{EMOJI_CROSS} Время вышло, отмена.")
                return

            text = decision.content.strip().lower()
            if text == "ok":
                await self._publish_message(interaction)
                return
            elif text == "edit":
                await self._run_wizard(interaction)
                return
            elif text == "cancel":
                await interaction.channel.send(f"{EMOJI_CROSS} Создание розыгрыша отменено.")
                return
            else:
                await interaction.channel.send(
                    f"Напишите **ok** для подтверждения, **edit** для повторного заполнения или **cancel** для отмены."
                )

    async def _publish_message(self, interaction: nextcord.Interaction):
        payload = self._pending
        channel = self.bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel:
            await interaction.channel.send(f"{EMOJI_CROSS} Канал розыгрыша не найден.")
            return

        giveaway_id = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        embed = build_giveaway_embed(
            interaction.user,
            payload["description"],
            payload["prize"],
            payload["winners"],
            payload["end_ts"],
            0,
            payload["banner_url"],
        )

        view = JoinView(giveaway_id)
        for child in view.children:
            if isinstance(child, nextcord.ui.Button):
                child.custom_id = f"join:{giveaway_id}"

        msg = await channel.send(embed=embed, view=view)

        giveaways = load_json(DATA_PATH, {})
        giveaways[giveaway_id] = {
            "message_id": msg.id,
            "channel_id": channel.id,
            "author_id": payload["user_id"],
            "prize": payload["prize"],
            "winners": payload["winners"],
            "end_ts": payload["end_ts"],
            "participants": [],
            "past_winners": [],
            "finished": False,
        }
        save_json(DATA_PATH, giveaways)

        self.bot.add_view(JoinView(giveaway_id))
        await interaction.channel.send(f"{EMOJI_CHECK} Опубликовано в {channel.mention}.")

    # ---------- Завершение ----------
    @tasks.loop(seconds=30)
    async def check_loop(self):
        giveaways = load_json(DATA_PATH, {})
        now = datetime.now(timezone.utc)
        changed = False
        for gid, g in giveaways.items():
            if g.get("finished"):
                continue
            if now.timestamp() < g["end_ts"]:
                continue
            await self.finish_giveaway(gid, g)
            g["finished"] = True
            changed = True
        if changed:
            save_json(DATA_PATH, giveaways)

    async def finish_giveaway(self, gid: str, g: dict):
        channel = self.bot.get_channel(g["channel_id"])
        if not channel:
            return

        participants = g["participants"]
        winners_count = g["winners"]
        guild = channel.guild

        if not participants:
            await channel.send(f"{EMOJI_WARN} Розыгрыш **{g['prize']}** завершён, но участников не было.")
            return

        pool = participants.copy()
        winners_list = []
        for _ in range(min(winners_count, len(pool))):
            w = random.choice(pool)
            pool.remove(w)
            winners_list.append(w)

        g["past_winners"] = winners_list.copy()

        mentions = []
        for w in winners_list:
            member = guild.get_member(int(w)) if guild else None
            mentions.append(member.mention if member else f"<@{w}>")

        if len(mentions) == 1:
            text = (
                f"{EMOJI_CROWN} **Розыгрыш «{g['prize']}» завершён!**\n\n"
                f"{EMOJI_STAR} Победитель: {mentions[0]}"
            )
        else:
            text = (
                f"{EMOJI_CROWN} **Розыгрыш «{g['prize']}» завершён!**\n\n"
                + "\n".join(f"{EMOJI_STAR} {m}" for m in mentions)
            )

        view = RerollView(gid)
        for child in view.children:
            if isinstance(child, nextcord.ui.Button):
                child.custom_id = f"reroll:{gid}"

        msg = await channel.send(text, view=view)
        g["result_message_id"] = msg.id
        self.bot.add_view(RerollView(gid))

def setup(bot):
    bot.add_cog(Giveaway(bot))