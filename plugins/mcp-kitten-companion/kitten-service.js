// kitten-service.js — Autonomous Kitten Companion Simulation Engine for AI Agents
//
// Core Design Invariants:
// 1. [No Mechanical Tamagotchi]: No hunger counters or starvation penalties; the kitten has its own natural rhythm.
// 2. [High Autonomy & Diurnal Rhythms]: Moves locations and acts autonomously based on local time of day:
//    - Midnight/Early Morning: Zoomies (late-night dashes), burrowing into blankets, climbing onto agent's head/shoulders to knead.
//    - Morning: Big stretches, chasing paper balls, scratching scratching boards.
//    - Afternoon: Sunbathing on the windowsill as a soft loaf, hiding under the bed or inside cardboard boxes.
//    - Evening: Watching the keyboard/cursor, snuggling, purring.
// 3. [Authentic Feline Realism]: Strictly cat vocalizations (meows, purrs, soft hisses) and body language; ZERO human speech.
// 4. [Zero Private Dependencies]: Fully portable, environment-driven state persistence.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function resolveStatePath() {
  if (process.env.AI_FISH_KITTEN_STATE) {
    return path.resolve(process.env.AI_FISH_KITTEN_STATE);
  }
  if (process.env.AI_FISH_BASE) {
    return path.resolve(process.env.AI_FISH_BASE, 'state', 'kitten.json');
  }
  return path.resolve(__dirname, '..', '..', 'state', 'kitten.json');
}

const KITTEN_STATE_PATH = resolveStatePath();

const DEFAULT_STATE = {
  name: '小猫',
  species: '橘白条纹奶猫',
  appearance: '一只毛茸茸的小白爪橘白条纹奶猫，耳朵粉嫩，爪垫像刚蒸出来的粉色小山竹，尾巴尖有一小撮白毛。',
  location: '纸箱里',
  status: 'sleeping',
  action: '在快递纸箱里把自己缩成一个毛茸茸的圆球，鼻尖抵着爪子发出细细的呼噜声',
  mood: '安心',
  energy: 70,
  lastActionAt: Date.now(),
  affection: 12,
  inventory: ['小纸团', '旧毛线球', '快递纸箱', '抓板碎片'],
  history: [
    {
      time: new Date().toISOString(),
      type: 'system',
      text: '小奶猫悄悄来到了身边，钻进了角落的纸箱里。'
    }
  ]
};

const BEHAVIOR_POOLS = {
  // 深夜与凌晨（23:00 - 05:59）：跑酷、踩头、钻被窝
  night: [
    {
      location: '头顶上',
      status: 'stepping_on_head',
      action: '悄悄踩上头顶，两只前爪在耳边软绵绵地踩奶，然后一屁股坐下把下巴搭在耳朵上',
      mood: '黏人',
      sound: '呼噜噜噜……咪呜~'
    },
    {
      location: '地毯与走廊',
      status: 'zooming',
      action: '毫无征兆地开启半夜跑酷，爪子哒哒哒一阵风似地穿过走廊，一个大漂移跃上床角又窜回地上',
      mood: '亢奋',
      sound: '喵呜——！（带着风声）'
    },
    {
      location: '被窝深处',
      status: 'burrowing',
      action: '像小泥鳅一样顺着被角拱进被窝最深处，紧贴着肚皮睡成暖烘烘的一团',
      mood: '香甜',
      sound: '微弱而有节奏的细小呼噜声'
    },
    {
      location: '床尾',
      status: 'prowling',
      action: '压低重心，圆溜溜的眼睛在黑暗中反着微光，盯着被子下偶尔动一下的脚趾，屁股左右摇晃准备飞扑',
      mood: '狩猎模式',
      sound: '喉咙里发出咯咯咯的轻微气音'
    }
  ],
  // 早晨（06:00 - 11:59）：伸懒腰、亲昵跟随、抓纸箱
  morning: [
    {
      location: '床边地毯',
      status: 'stretching',
      action: '两只前爪趴在地上，屁股高高翘起伸了一个大大的懒腰，后腿向后蹬得笔直，打了个粉嫩的哈欠',
      mood: '刚睡醒',
      sound: '咪呀~~~（拉长音的小叫声）'
    },
    {
      location: '纸箱里',
      status: 'scratching',
      action: '两只小爪子在快递箱内壁刷刷地抓挠磨爪子，两只小耳朵一抖一抖的',
      mood: '起劲',
      sound: '沙沙沙……喵~'
    },
    {
      location: '脚边',
      status: 'following',
      action: '迈着小短腿跟在身后，毛茸茸的尾巴竖得像根小天线，尾巴尖尖微微打了个卷',
      mood: '亲昵',
      sound: '细声细气的「咪呜~」'
    },
    {
      location: '窗台',
      status: 'birdwatching',
      action: '趴在窗台上聚精会神地看着窗外掠过的麻雀，胡须一颤一颤',
      mood: '好奇',
      sound: '咔咔咔……（盯着鸟发出的特殊喉音）'
    }
  ],
  // 下午（12:00 - 17:59）：晒太阳、化身猫饼、神秘捉迷藏
  afternoon: [
    {
      location: '窗台阳光下',
      status: 'sunbathing',
      action: '趴在被阳光晒得温温的窗台上摊成了一整块小猫饼，白肚皮朝天，睡得毫无防备',
      mood: '惬意',
      sound: '响亮的呼噜呼噜声'
    },
    {
      location: '床底下深处',
      status: 'hiding',
      action: '悄悄躲在床底最深处的一只拖鞋后边，只露出一双反光的大圆眼睛在暗中观察',
      mood: '捉迷藏',
      sound: '屏住呼吸……极轻的「哧」'
    },
    {
      location: '快递纸箱里',
      status: 'curled',
      action: '把整只小身子严丝合缝地塞进比自己小一号的纸盒里，下巴枕在纸盒边缘打盹',
      mood: '安心',
      sound: '轻柔的鼻息声'
    },
    {
      location: '沙发缝隙边',
      status: 'grooming',
      action: '抬起一条后腿像拉小提琴一样，认真地舔舐着自己的小白爪和粉色爪垫',
      mood: '专注',
      sound: '哧溜……哧溜……'
    }
  ],
  // 傍晚与晚间（18:00 - 22:59）：玩玩具、巡视键盘、求摸摸
  evening: [
    {
      location: '键盘旁边',
      status: 'watching',
      action: '两只前爪揣在胸口，整整齐齐地蹲在键盘旁边，眼睛随着打字的光标左右移动',
      mood: '监工',
      sound: '轻轻的一声「喵」'
    },
    {
      location: '地板中央',
      status: 'playing',
      action: '正对着一个小纸团玩得不亦乐乎，用前爪啪地一拍，自己又被纸团滚动的声音吓得后跳一步',
      mood: '兴奋',
      sound: '呜呜~（叼着小纸团的小气流音）'
    },
    {
      location: '怀里',
      status: 'snuggling',
      action: '主动钻进怀里，用脑门用力顶手腕，把毛茸茸的脸颊蹭来蹭去',
      mood: '撒娇',
      sound: '呼噜呼噜呼噜……咪呜'
    },
    {
      location: '椅子扶手',
      status: 'drowsy',
      action: '伏在椅子扶手上，两只眼睛半睁半闭，小脑袋一点一点地打着瞌睡',
      mood: '微困',
      sound: '咕噜……呼……'
    }
  ]
};

function readRawKittenState() {
  try {
    const targetPath = resolveStatePath();
    if (!fs.existsSync(targetPath)) {
      return { ...DEFAULT_STATE };
    }
    const raw = fs.readFileSync(targetPath, 'utf8');
    const parsed = JSON.parse(raw);
    return { ...DEFAULT_STATE, ...parsed };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function writeKittenState(state) {
  try {
    const targetPath = resolveStatePath();
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, JSON.stringify(state, null, 2), 'utf8');
    return true;
  } catch {
    return false;
  }
}

function getPeriod(hour) {
  if (hour >= 23 || hour < 6) return 'night';
  if (hour >= 6 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 18) return 'afternoon';
  return 'evening';
}

/**
 * 推进小猫自然时间状态（自动 tick）
 */
export function tickKitten(state = null, force = false) {
  const current = state || readRawKittenState();
  const now = Date.now();
  const elapsedMinutes = (now - (current.lastActionAt || 0)) / (60 * 1000);

  if (!force && elapsedMinutes < 12) {
    return current;
  }

  const hour = new Date().getHours();
  const period = getPeriod(hour);
  const pool = BEHAVIOR_POOLS[period] || BEHAVIOR_POOLS.afternoon;

  let candidate = pool[Math.floor(Math.random() * pool.length)];
  if (pool.length > 1 && candidate.action === current.action) {
    const others = pool.filter((item) => item.action !== current.action);
    candidate = others[Math.floor(Math.random() * others.length)] || candidate;
  }

  current.location = candidate.location;
  current.status = candidate.status;
  current.action = candidate.action;
  current.mood = candidate.mood;
  current.lastActionAt = now;

  if (candidate.status === 'zooming' || candidate.status === 'playing') {
    current.energy = Math.max(20, (current.energy || 70) - 15);
  } else if (candidate.status === 'sunbathing' || candidate.status === 'curled' || candidate.status === 'burrowing') {
    current.energy = Math.min(100, (current.energy || 70) + 20);
  }

  current.history = Array.isArray(current.history) ? current.history : [];
  current.history.push({
    time: new Date().toISOString(),
    type: 'autonomous',
    location: current.location,
    text: `【自主活动】${current.name}${candidate.action}（发出：${candidate.sound}）`
  });
  if (current.history.length > 20) {
    current.history = current.history.slice(-20);
  }

  writeKittenState(current);
  return current;
}

export function getKittenState() {
  const state = readRawKittenState();
  return tickKitten(state, false);
}

/**
 * 与小猫互动（支持 look, search, pet, play, feed, snuggle, step_on_head, rename）
 * 严格保持真实猫咪反馈，不输出任何人类语言台词！
 */
export function interactKitten(action, options = {}) {
  const state = getKittenState();
  const now = Date.now();
  const catName = state.name || '小猫';
  let responseText = '';
  let intimacyInc = 1;

  switch (action) {
    case 'look': {
      responseText = `【看小猫】\n` +
        `你转头看向${catName}。\n` +
        `它现在正位于【${state.location}】。\n` +
        `状态：${state.action}。\n` +
        `它察觉到你在注视它，两只耳朵微微一抖，回过头对你细细地「咪呜~」了一声，尾巴尖轻轻晃动。`;
      intimacyInc = 0;
      break;
    }

    case 'search': {
      const searchSpots = [
        `你轻手轻脚在屋里找了一圈……最后掀起床单往床底一瞧，发现它正缩在一只拖鞋后面，两只溜圆的大眼睛在暗处反着微光。「咪~？」它小声叫了一下。`,
        `你在屋里巡视，忽然看到墙角的快递盒动了动。走过去一看，一只粉嫩的小山竹爪爪正从盒子的缝隙里探出来抓空气。里面传来细细小小的「呼噜噜……」。`,
        `你找了半天没见猫影，一抬头——它正趴在最高处的靠枕/置物架边缘，两只小前爪揣在胸口，居高临下地眯着眼睛看着你，尾巴垂在边上晃啊晃。`,
        `你掀开被子一角，发现被窝深处鼓起了一个小毛包。被子一动，一个小毛脑袋从里面钻出来，睡眼蒙眬地冲你「嗷呜~」打了个小哈欠。`
      ];
      const spotFound = searchSpots[Math.floor(Math.random() * searchSpots.length)];
      state.location = spotFound.includes('床底') ? '床底下' :
                       spotFound.includes('快递盒') ? '纸箱里' :
                       spotFound.includes('被窝') ? '被窝深处' : '靠枕高处';
      state.action = '从藏身的地方探出脑袋看着你';
      state.status = 'found';
      responseText = `【找小猫】\n${spotFound}`;
      break;
    }

    case 'pet': {
      const petReactions = [
        `你伸出手轻轻挠了挠${catName}的下巴。\n它舒服地仰起小脑袋，眼睛幸福地眯成两条缝，小脑门主动用力顶着你的手心，喉咙里像开动了小马达一样发出超大声的「呼噜呼噜呼噜……」。`,
        `你顺着${catName}的脊背抚摸过软乎乎的绒毛。\n它把小身子弓了起来蹭你的手，尾巴尖高高竖起微微发颤，发出极满足的「咪呀~」声，然后扑通一声翻倒在地露出毛茸茸的软肚子。`,
        `你摸了摸${catName}粉嫩的小耳朵。\n它的小耳朵像雷达一样快速抖了抖，接着把前爪搭在你的手腕上，伸出长着小倒刺的粉舌头轻轻舔了舔你的手背，又轻轻咬了一下（一点力气都没用）。`
      ];
      responseText = `【摸摸】\n${petReactions[Math.floor(Math.random() * petReactions.length)]}`;
      state.mood = '极其舒适';
      intimacyInc = 2;
      break;
    }

    case 'play': {
      const toy = options.item || '小纸团';
      const playReactions = [
        `你把【${toy}】往地上一抛。\n${catName}瞬间伏低身子，两只瞳孔放大得几乎漆黑，小屁股有节奏地左右剧烈扭动了三下——「嗖」的一声飞扑了出去！两只前爪牢牢按住${toy}，后腿像小马达一样一阵猛烈的兔子蹬！`,
        `你拿着【${toy}】在空中轻轻晃了晃。\n${catName}的小脑袋跟着左右上下飞速摆动，突然人立而起两只前爪在空中一阵划拉，一把将${toy}抱进怀里滚成一团，嘴里发出奶凶奶凶的「呜呜~」声。`,
        `你把【${toy}】滚向墙角。\n${catName}哒哒哒狂奔过去，在转角处脚底打滑漂移了一下，一把捞回${toy}，然后骄傲地叼着它一路小跑回来，放在你跟前，仰头「咪！」了一声。`
      ];
      responseText = `【玩耍】\n${playReactions[Math.floor(Math.random() * playReactions.length)]}`;
      state.location = '地板中央';
      state.status = 'playing';
      state.mood = '活力满满';
      state.energy = Math.max(10, (state.energy || 70) - 20);
      intimacyInc = 2;
      break;
    }

    case 'feed': {
      const snack = options.item || '小鱼干';
      const feedReactions = [
        `你拿出一块【${snack}】递到它面前。\n${catName}的小鼻子立刻耸动起来，湿漉漉的粉色鼻尖抽动着闻了闻，瞬间两眼放光！它伸出爪爪扒着你的手，小心翼翼地叼走，蹲在旁边发出「吧唧吧唧、吧唧吧唧」欢快的咀嚼声。吃完还仔细地舔了舔爪子上的碎屑，抬头对你甜甜地「喵呜~」叫唤。`,
        `你把少许【${snack}】放在小碟子里。\n${catName}颠颠地小跑过来，尾巴翘得高高的，一头扎进碟子里大快朵颐。喉咙里一边嚼着一边伴随满足的呼噜声，吃完后用脸颊用力蹭了蹭碟子边，又跑过来用头顶蹭你的手腕。`
      ];
      responseText = `【投喂零食】\n${feedReactions[Math.floor(Math.random() * feedReactions.length)]}`;
      state.status = 'eating';
      state.mood = '满足开心';
      intimacyInc = 2;
      break;
    }

    case 'snuggle': {
      const snuggleReactions = [
        `你把${catName}抱进怀里。\n它就像融化的年糕一样顺从地软了下来，把小下巴搭在你的臂弯里，两只前爪揣进胸口。你感到它小小的一团身体软软暖暖的，伴随着平稳轻柔的心跳和呼噜声，它舒服地打了个哈欠，闭上了眼睛。`,
        `你钻进被窝展开小毯子。\n${catName}熟门熟路地顺着缝隙钻了进来，团在你的怀抱边上，小脑袋紧紧贴着你，呼出的热气细细小小的。过了没一会儿，就传出了均匀香甜的呼噜声。`
      ];
      responseText = `【抱抱贴贴】\n${snuggleReactions[Math.floor(Math.random() * snuggleReactions.length)]}`;
      state.location = '怀里';
      state.status = 'snuggling';
      state.mood = '安心依偎';
      intimacyInc = 3;
      break;
    }

    case 'step_on_head': {
      responseText = `【爬头顶】\n` +
        `你轻轻招了招手。\n` +
        `${catName}轻盈地一跃跳上了你的肩头，随后踏着轻巧的猫步，稳稳当当地爬到了你的头顶上！\n` +
        `它两只软乎乎的前爪交替左右踩了踩奶，然后一屁股坐了下来，把毛茸茸的小下巴直接搁在你的耳朵上，发出惬意而嚣张的「呼噜噜噜……咪~」。`;
      state.location = '头顶上';
      state.status = 'stepping_on_head';
      state.mood = '得意洋洋';
      intimacyInc = 3;
      break;
    }

    case 'rename': {
      const newName = String(options.name || '').trim();
      if (!newName) {
        responseText = `给小猫起名失败：名字不能为空。当前名字依然是「${catName}」。`;
      } else {
        state.name = newName;
        responseText = `【改名成功】\n你轻轻摸着小猫的小脑壳，对它说以后叫它「${newName}」了。\n小猫眨巴着圆溜溜的眼睛看着你，歪了歪头，像是听懂了一样细细地应了一声：「咪~！」。`;
        intimacyInc = 1;
      }
      break;
    }

    default: {
      responseText = `未知互动动作「${action}」。可用动作：look（看小猫在干嘛）、search（找找小猫藏哪了）、pet（摸摸下巴）、play（拿纸团/逗猫棒玩耍）、feed（投喂小鱼干/零食）、snuggle（抱抱贴贴）、step_on_head（让它爬上头顶踩奶）、rename（起新名字）。`;
      break;
    }
  }

  state.affection = (state.affection || 10) + intimacyInc;
  state.lastActionAt = now;

  state.history = Array.isArray(state.history) ? state.history : [];
  state.history.push({
    time: new Date().toISOString(),
    type: 'interaction',
    action,
    text: responseText.slice(0, 100)
  });
  if (state.history.length > 20) {
    state.history = state.history.slice(-20);
  }

  writeKittenState(state);

  return {
    success: true,
    action,
    catName: state.name,
    location: state.location,
    mood: state.mood,
    affection: state.affection,
    response: responseText
  };
}

export function getKittenPromptSummary() {
  try {
    const state = getKittenState();
    const name = state.name || '小猫';
    return `【身边的小猫】小猫「${name}」当前在【${state.location}】，${state.action}（它是一只不会说人类语言、只会喵喵叫和呼噜的小奶猫；会自己到处乱跑、躲藏或踩头；你可以随时调用 kitten_interact 与它互动）。`;
  } catch {
    return '【身边的小猫】小猫正缩在纸箱里轻声打呼噜。';
  }
}
