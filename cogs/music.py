import discord
from discord.ext import commands
from utils import Playlist, ServerInfo, ServerMusic, Song, save_info, send_notice, search, ERROR, WARNING, MESSAGE, SILVER
import asyncio
from time import sleep
from cogs.database import database


class music(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.database: database = self.client.get_cog('database')

    # check for force disconnect
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        server_music: ServerMusic = self.database.server_music[member.guild.id]
        if member == self.client.user:
            # if the bot disconnected
            if before.channel and not after.channel:
                if server_music.vc:
                    server_music.vc.stop()
                    await server_music.vc.disconnect()
                    server_music.vc.cleanup()
                    server_music.vc = None
                server_music.clear()
                server_music.is_playing = False
                server_music.current_song = None

    async def update_now_playing(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        prev_now_playing: discord.Message = server_music.now_playing

        if server_music.current_song:
            song = server_music.current_song

            embed = discord.Embed(
                title='Now playing',
                description=f'[**{song.title}**]({song.link})',
                color=SILVER
            )
            server_music.now_playing = await ctx.channel.send(embed=embed)

        if prev_now_playing:
            await prev_now_playing.delete()

    def playlist_embed(self, playlist: Playlist):
        embed = discord.Embed(title='Playlist Added', color=SILVER)
        embed.add_field(
            name='Playlist',
            value=f'[{playlist.title}]({playlist.url})', inline=False
        )
        embed.add_field(name='Playlist Length', value=f'{playlist.duration}')
        embed.add_field(name='Tracks', value=f'{playlist.track_num}')
        embed.set_thumbnail(
            url=playlist.thumbnail if 'https://' in playlist.thumbnail and '.' in playlist.thumbnail else discord.Embed.Empty
        )
        return embed

    def added_embed(self, song: Song, server_music: ServerMusic):
        thumbnail = song.thumbnail if song.thumbnail else discord.Embed.Empty

        if server_music.vc.is_paused():
            server_music.current_song.reset_time()

        wait_time = server_music.current_song.duration - \
            server_music.current_song.progress
        for song in server_music.queue:
            wait_time += song.duration
        wait_time -= song.duration

        embed = discord.Embed(title='Added Track', color=SILVER)
        embed.add_field(
            name='Track',
            value=f'[{song.title}]({song.link})',
            inline=False
        )
        embed.add_field(name='Estimated wait time', value=wait_time)
        embed.add_field(name='Track Length', value=song.duration)
        embed.add_field(name='Position in queue', value=len(server_music))
        embed.set_thumbnail(url=thumbnail)
        return embed

    def song_info_embed(self, pos: int, server_music: ServerMusic):
        song = server_music.queue[pos]
        thumbnail = song.thumbnail if song.thumbnail else discord.Embed.Empty

        embed = discord.Embed(
            title=song.title,
            url=song.link,
            color=SILVER
        )
        embed.add_field(name='Track Length', value=song.duration)
        embed.add_field(name='Position in queue', value=pos+1)
        embed.add_field(name='Links', value=song.links)

        embed.set_thumbnail(url=thumbnail)
        return embed

    def current_info_embed(self, server_music: ServerMusic):
        if server_music.vc.is_paused():
            server_music.current_song.reset_time()

        song = server_music.current_song
        thumbnail = song.thumbnail if song.thumbnail else discord.Embed.Empty

        embed = discord.Embed(
            title=song.title,
            description=server_music.current_song.progress_bar,
            url=song.link,
            color=SILVER
        )
        embed.add_field(name='Track Length', value=song.duration)
        embed.add_field(name='Links', value=song.links)
        embed.add_field(
            name='Progress',
            value=server_music.current_song.progress_str
        )
        embed.set_thumbnail(url=thumbnail)
        return embed

    # connect to voice channel
    async def connect(self, ctx: commands.Context) -> bool:
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if not server_music.vc:
            if ctx.author.voice:
                server_music.vc = await ctx.author.voice.channel.connect()
                return True
            else:
                await send_notice(ctx, 'You\'re not in a voice channel.')
                return False
        else:
            await server_music.vc.move_to(ctx.author.voice.channel)
            return True

    # play loop
    def play_loop(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        # song looping logic
        if server_info.loop != 'disabled' and server_music.current_song:
            if server_music.current_song.url and not server_music.current_song.source:
                if server_info.loop == 'queue':
                    server_music.queue.append(server_music.current_song)
                elif server_info.loop == 'song':
                    server_music.queue.insert(0, server_music.current_song)

        if len(server_music.queue) > 0:
            server_music.is_playing = True

            server_music.current_song = server_music.queue[0]
            server_music.queue.pop(0)

            try:
                source = server_music.current_song.extract_source()
                source = discord.PCMVolumeTransformer(
                    source,
                    server_info.volume/100
                )
                server_music.vc.play(
                    source,
                    after=lambda _: self.play_loop(ctx)
                )
                server_music.current_song.reset_time()
                asyncio.run_coroutine_threadsafe(
                    self.update_now_playing(ctx),
                    self.client.loop
                )
            except Exception as e:
                print(e)
                self.play_loop(ctx)

        else:
            server_music.is_playing = False
            server_music.current_song = None
            asyncio.run_coroutine_threadsafe(
                self.update_now_playing(ctx),
                self.client.loop
            )
            elapsed = 0
            while True:
                sleep(1)
                elapsed += 1
                if server_music.is_playing and not server_music.vc.is_paused():
                    break
                if elapsed == 600:
                    if not server_music.is_playing and server_music.vc:
                        asyncio.run_coroutine_threadsafe(
                            server_music.vc.disconnect(),
                            self.client.loop
                        )
                if not server_music.vc or not server_music.vc.is_connected():
                    break

    @commands.group(aliases=['p'], invoke_without_command=True, help='<song name/url>', description='Plays a song.\n`[Music]`')
    async def play(self, ctx: commands.Context, *, query: str):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        # search song from query
        songs, playlist = search(query)
        if playlist:
            embed = self.playlist_embed(playlist)
            await ctx.send(embed=embed)

        # Add songs to queue
        if songs:
            server_music.queue += songs
            if not server_music.is_playing:
                # join voice channel
                connected = await self.connect(ctx)
                # play music
                if connected:
                    self.play_loop(ctx)
            else:
                if not playlist:
                    embed = self.added_embed(songs[0], server_music)
                    await ctx.send(embed=embed)
        else:
            await send_notice(ctx, 'Could not play song.')

    @play.command(name='file', aliases=['f'], help='', description='Plays the file attached to the message.\n`[Music]`')
    async def play_file(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        message: discord.Message = ctx.message
        if message.attachments:
            attachment = message.attachments[0]
            try:
                songs, playlist = search(attachment.url)
                # Add songs to queue
                if songs:
                    server_music.queue += songs
                    if not server_music.is_playing:
                        # join voice channel
                        connected = await self.connect(ctx)
                        # play music
                        if connected:
                            self.play_loop(ctx)
                    else:
                        if not playlist:
                            embed = self.added_embed(songs[0], server_music)
                            await ctx.send(embed=embed)
                else:
                    await send_notice(ctx, 'Could not play song.')
            except Exception as e:
                await send_notice(ctx, str(e))
        else:
            await send_notice(ctx, 'No file provided.')

    @commands.command(aliases=['break'], help='', description='Pauses the current playing song.\n`[Music]`')
    async def pause(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if not server_music.vc.is_paused():
                server_music.current_song.save_progress()
                server_music.vc.pause()
                await send_notice(ctx, 'Paused the song.', notice_type=MESSAGE)
            else:
                await send_notice(ctx, 'The song is already paused.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['continue', 'unpause'], help='', description='Resumes the current paused song.\n`[Music]`')
    async def resume(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.vc.is_paused():
                server_music.current_song.reset_time()
                server_music.vc.resume()
                await send_notice(ctx, 'Resumed the song.', notice_type=MESSAGE)
            else:
                await send_notice(ctx, 'The song is not paused.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['s', 'next'], help='|<trackNumber>', description='Lets you skip the current song.\n`[Music]`|Skips to a specific track in the queue.\n`[Music]`')
    async def skip(self, ctx: commands.Context, skip_amount: int = 0):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if skip_amount:
                skip_idx = skip_amount - 1
                queue_len = len(server_music.queue)

                if queue_len == 0:
                    await send_notice(ctx, 'There is currently no song in the queue.', notice_type=WARNING)
                elif skip_idx < queue_len:
                    server_music.queue = server_music.queue[skip_idx:]
                    await send_notice(ctx, f'Skipped `{skip_amount}` songs.', ctx.channel, notice_type=MESSAGE)
                    server_music.vc.stop()
                else:
                    server_music.queue = server_music.queue[queue_len-1:]
                    await send_notice(ctx, f'Skipped `{queue_len}` songs.', ctx.channel, notice_type=MESSAGE)
                    server_music.vc.stop()
            # skip current song
            else:
                server_music.vc.stop()
                await ctx.message.add_reaction('✅')
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(help='', description='Stops all the songs.\n`[Music]`')
    async def stop(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            server_music.clear()
            server_music.vc.stop()
            await ctx.message.add_reaction('✅')
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['c', 'empty', 'removeall'], help='', description='Clears the current queue.\n`[Music]`')
    async def clear(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.clear()
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['si', 'np', 'song', 'now', 'nowplaying'], help='|<song number>', description='Shows details of the song currently being played.\n`[Music]`|Shows the detail of a specific song in the queue.\n`[Music]`')
    async def songinfo(self, ctx: commands.Context, song_num: int = 0):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if song_num:
                if server_music.queue:
                    await ctx.send(embed=self.song_info_embed(song_num-1, server_music))
                else:
                    await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
            else:
                await ctx.send(embed=self.current_info_embed(server_music))
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['rp', 'restart'], help='', description='Replay the current song.\n`[Music]`')
    async def replay(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            server_music.current_song.reset_time()
            server_music.queue.insert(0, server_music.current_song)
            server_music.vc.stop()
            await ctx.message.add_reaction('✅')
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['sh'], help='', description='Shuffle the queue.\n`[Music]`')
    async def shuffle(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.shuffle()
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(help='', description='Reverse the current queue.\n`[Music]`')
    async def reverse(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.reverse()
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.group(aliases=['mv'], invoke_without_command=True, help='<song number>|<from> <to>', description='Move the selected song to the top of the queue.\n`[Music]`|Move the selected song to the provided position.\n`[Music]`')
    async def move(self, ctx: commands.Context, pos1: int, pos2: int = 1):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.move(pos1-1, pos2-1)
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @move.command(name='swap', aliases=['swp'], help='<first> <second>', description='Swap track positions in the queue.\n`[Music]`')
    async def move_swap(self, ctx: commands.Context, pos1: int, pos2: int):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.swap(pos1-1, pos2-1)
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @move.command(name='last', help='', description='Move the last track in the queue to the top.\n`[Music]`')
    async def move_last(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.move(-1, 0)
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.group(aliases=['rm', 'del', 'delete'], invoke_without_command=True, help='<song number>', description='Remove a specific song from the queue.\n`[Music]`')
    async def remove(self, ctx: commands.Context, pos: int):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.remove(pos-1)
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @remove.command(name='range', aliases=['rg'], help='<from> <to>', description='Remove a range of tracks from the queue.\n`[Music]`')
    async def remove_range(self, ctx: commands.Context, pos1: int, pos2: int):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.remove(slice(pos1-1, pos2))
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @remove.command(name='last', help='', description='Remove the last track in the queue.\n`[Music]`')
    async def remove_last(self, ctx: commands.Context):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            if server_music.queue:
                server_music.remove(-1)
                await ctx.message.add_reaction('✅')
            else:
                await send_notice(ctx, 'Song queue is empty.', notice_type=WARNING)
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.group(aliases=['lp'], invoke_without_command=True, help='', description='Cycles through all three loop modes (queue, song, off).\n`[Music]`')
    async def loop(self, ctx: commands.Context):
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        server_info.cycle_loop()
        await send_notice(ctx, f'Looping `{server_info.loop}`', notice_type=MESSAGE)
        save_info(self.client)

    @loop.command(name='queue', aliases=['q'], help='', description='Loop the queue.\n`[Music]`')
    async def loop_queue(self, ctx: commands.Context):
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        server_info.loop = 'queue'
        await send_notice(ctx, f'Looping `{server_info.loop}`', notice_type=MESSAGE)
        save_info(self.client)

    @loop.command(name='song', help='', description='Loop the current playing song.\n`[Music]`')
    async def loop_song(self, ctx: commands.Context):
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        server_info.loop = 'song'
        await send_notice(ctx, f'Looping `{server_info.loop}`', notice_type=MESSAGE)
        save_info(self.client)

    @loop.command(name='off', aliases=['disable'], help='', description='Turn looping off.\n`[Music]`')
    async def loop_off(self, ctx: commands.Context):
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        server_info.loop = 'disabled'
        await send_notice(ctx, f'Looping `{server_info.loop}`', notice_type=MESSAGE)
        save_info(self.client)

    @commands.command(aliases=['sk'], help='mm:ss', description='Seeks to a specific position in the current song.\n`[Music]`')
    async def seek(self, ctx: commands.Context, pos: str):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        if server_music.is_playing:
            FFMPEG_OPTIONS = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': f'-vn -ss {pos}'
            }
            url = server_music.current_song.url
            source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            server_music.current_song.source = source
            server_music.current_song.set_progress_str(pos)

            server_music.queue.insert(0, server_music.current_song)
            server_music.vc.stop()
            await ctx.message.add_reaction('✅')
        else:
            await send_notice(ctx, 'The bot is currently not playing.', notice_type=ERROR)

    @commands.command(aliases=['vol', 'v'], help='|0-200', description='Show the current volume.\n`[Music]`|Change the bot\'s output volume.\n`[Music]`')
    async def volume(self, ctx: commands.Context, vol: float=None):
        server_music: ServerMusic = self.database.server_music[ctx.guild.id]
        server_info: ServerInfo = self.client.server_info[ctx.guild.id]
        if not vol:
            await send_notice(ctx, f'Volume is at `{server_info.volume}%`.', notice_type=MESSAGE)
        else:
            if vol < 0:
                await send_notice(ctx, 'Volume too low.', notice_type=ERROR)
            elif vol > 200:
                await send_notice(ctx, 'Volume too high.', notice_type=ERROR)
            else:
                server_info.volume = vol
                await send_notice(ctx, f'Volume set to `{vol}%`.', notice_type=WARNING)
                save_info(self.client)
                if server_music.is_playing:
                    server_music.vc.source.volume = vol/100

def setup(client: commands.Bot):
    client.add_cog(music(client))
