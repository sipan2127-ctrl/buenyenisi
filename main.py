import discord
from discord.ext import commands
import datetime
import asyncio
from collections import defaultdict, deque
import os
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.bans = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- AĞIRLIK YAPMAYAN HIZLI HAFIZA ---
spam_tracker = defaultdict(lambda: deque(maxlen=5))
dup_tracker = defaultdict(lambda: deque(maxlen=7))

channel_logs = defaultdict(list)
ban_logs = defaultdict(list)

afk_users = {}
spam_koruma_aktif = True

# --- ÖNBELLEKLİ VE HIZLI ROL ÇEKME ---
async def remove_all_roles(member: discord.Member, reason: str):
    try:
        roles_to_remove = [r for r in member.roles if r != member.guild.default_role and not r.managed]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=reason)
            print(f"[GUARD] {member.display_name} -> Rolleri alındı. Sebep: {reason}")
    except Exception as e:
        print(f"[GUARD HATA] {e}")

@bot.event
async def on_ready():
    print(f'{bot.user} ultra hızlı modda aktif!')

# --- OPTİMİZE EDİLMİŞ MESAJ ETKİNLİĞİ ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    content_lower = message.content.lower().strip()

    # 1. SA-AS
    if content_lower in ('sa', 'sa.', 'sa!'):
        await message.channel.send('Aleyküm selam')

    # 2. AFK Kontrol
    author_id = message.author.id
    if author_id in afk_users:
        del afk_users[author_id]
        await message.channel.send(f'{message.author.mention}, artık AFK değilsin!')

    if message.mentions:
        for mention in message.mentions:
            if mention.id in afk_users:
                await message.channel.send(f'{mention.display_name} şu anda AFK. (Sebep: {afk_users[mention.id]})')

    # 3. Hızlı Spam Koruma
    global spam_koruma_aktif
    if spam_koruma_aktif:
        now_ts = datetime.datetime.utcnow().timestamp()

        # Hız kontrolü (5sn / 5 mesaj)
        u_times = spam_tracker[author_id]
        u_times.append(now_ts)
        if len(u_times) == 5 and (u_times[-1] - u_times[0]) <= 5:
            u_times.clear()
            asyncio.create_task(message.author.timeout(datetime.timedelta(minutes=10), reason="Spam Hız Limit"))
            await message.channel.send(f'{message.author.mention}, 5 saniyede 5 mesaj attığın için 10 dk mute yedin!')

        # Tekrar kontrolü (7 aynı mesaj)
        u_msgs = dup_tracker[author_id]
        u_msgs.append(message.content)
        if len(u_msgs) == 7 and len(set(u_msgs)) == 1:
            u_msgs.clear()
            asyncio.create_task(message.author.timeout(datetime.timedelta(minutes=10), reason="Spam Tekrar Limit"))
            await message.channel.send(f'{message.author.mention}, aynı cümleyi 7 kere yazdığın için 10 dk mute yedin!')

    await bot.process_commands(message)

# --- OPTİMİZE EDİLMİŞ GUARD ---
async def check_channel_limit(guild):
    now_ts = datetime.datetime.utcnow().timestamp()
    try:
        async for entry in guild.audit_logs(limit=1):
            if entry.action in (discord.AuditLogAction.channel_create, discord.AuditLogAction.channel_delete):
                user = entry.user
                if user and not user.bot:
                    logs = channel_logs[user.id]
                    logs.append(now_ts)
                    # 24 saat filtresi (86400 sn)
                    channel_logs[user.id] = [t for t in logs if (now_ts - t) <= 86400]
                    if len(channel_logs[user.id]) >= 10:
                        member = guild.get_member(user.id)
                        if member:
                            asyncio.create_task(remove_all_roles(member, "24 saatte 10 kanal limiti"))
    except Exception:
        pass

@bot.event
async def on_guild_channel_create(channel):
    asyncio.create_task(check_channel_limit(channel.guild))

@bot.event
async def on_guild_channel_delete(channel):
    asyncio.create_task(check_channel_limit(channel.guild))

@bot.event
async def on_member_ban(guild, user):
    now_ts = datetime.datetime.utcnow().timestamp()
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
            mod = entry.user
            if mod and not mod.bot:
                logs = ban_logs[mod.id]
                logs.append(now_ts)
                ban_logs[mod.id] = [t for t in logs if (now_ts - t) <= 86400]
                if len(ban_logs[mod.id]) >= 5:
                    member = guild.get_member(mod.id)
                    if member:
                        asyncio.create_task(remove_all_roles(member, "24 saatte 5 ban limiti"))
    except Exception:
        pass

@bot.event
async def on_guild_update(before, after):
    if before.name != after.name or before.vanity_url_code != after.vanity_url_code:
        try:
            async for entry in after.audit_logs(action=discord.AuditLogAction.guild_update, limit=1):
                user = entry.user
                if user and not user.bot:
                    member = after.get_member(user.id)
                    if member:
                        asyncio.create_task(remove_all_roles(member, "Sunucu adı/URL değiştirme"))
        except Exception:
            pass

# --- KOMUTLAR ---
@bot.command()
@commands.has_permissions(manage_roles=True)
async def rol(ctx, member: discord.Member, role: discord.Role):
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f'{member.mention} kullanıcısından **{role.name}** alındı.')
    else:
        await member.add_roles(role)
        await ctx.send(f'{member.mention} kullanıcısına **{role.name}** verildi.')

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, dakika: int = 10):
    await member.timeout(datetime.timedelta(minutes=dakika))
    await ctx.send(f'{member.mention} **{dakika} dakika** susturuldu.')

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f'{member.mention} susturması kaldırıldı.')

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Belirtilmedi"):
    await member.ban(reason=reason)
    await ctx.send(f'{member.mention} banlandı. Sebep: {reason}')

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(f'**{user.name}** yasaklaması kaldırıldı.')

@bot.command(name="sunucu-bilgi")
async def sunucu_bilgi(ctx):
    g = ctx.guild
    embed = discord.Embed(title=f"{g.name} Bilgileri", color=discord.Color.blue())
    embed.add_field(name="Üye", value=str(g.member_count))
    embed.add_field(name="Sahip", value=str(g.owner))
    embed.add_field(name="Kuruluş", value=g.created_at.strftime("%d/%m/%Y"))
    await ctx.send(embed=embed)

@bot.command(name="kisi-bilgi")
async def kisi_bilgi(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"{member.name} Bilgileri", color=discord.Color.green())
    embed.add_field(name="Sunucuya Katılım", value=member.joined_at.strftime("%d/%m/%Y"))
    embed.add_field(name="Hesap Açılış", value=member.created_at.strftime("%d/%m/%Y"))
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def spamkoruma(ctx, durum: str):
    global spam_koruma_aktif
    spam_koruma_aktif = (durum.lower() == "acik")
    await ctx.send(f"Spam koruması: **{'AÇIK' if spam_koruma_aktif else 'KAPALI'}**")

@bot.command()
async def afk(ctx, *, reason="Belirtilmedi"):
    afk_users[ctx.author.id] = reason
    await ctx.send(f'{ctx.author.mention}, AFK moduna geçtin. Sebep: {reason}')

# Web sunucusu (Uptime için)
keep_alive()

# Botu başlat
token = os.getenv('DISCORD_TOKEN')
if token:
    bot.run(token)
