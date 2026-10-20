let currentCharacter = "";
let currentChatId = "";
let userName = "User";
let ws = null;
let wsReconnectDelay = 2000;
let wsReconnectTimer = null;
let currentMessageId = null;
let currentMessageDiv = null;
let historyOffset = 0;
const HISTORY_LIMIT = 50;
let isLoadingHistory = false;
let hasMoreHistory = true;
let avatarConfig = {};
let pendingRegenReload = false;
const STANDARD_EMOTIONS = [
    "admiration", "amusement", "anger", "annoyance", "approval", "caring",
    "confusion", "curiosity", "desire", "disappointment", "disapproval",
    "disgust", "embarrassment", "excitement", "fear", "gratitude", "grief",
    "love", "nervousness", "neutral", "optimism", "pride", "realization",
    "relief", "remorse", "surprise", "joy", "sadness"
];

const DEFAULT_EMOTION_MOTIONS = {
    admiration: "Happy", amusement: "Laugh", anger: "Anger", annoyance: "Anger",
    approval: "Happy", caring: "Idle", confusion: "Doubt", curiosity: "Doubt",
    desire: "Happy", disappointment: "Sad", disapproval: "Anger", disgust: "Anger",
    embarrassment: "Shame", excitement: "Happy", fear: "Cry", gratitude: "Happy",
    grief: "Cry", love: "Happy", nervousness: "Doubt", neutral: "Idle",
    optimism: "Happy", pride: "Pride", realization: "Surprise", relief: "Idle",
    remorse: "Sad", surprise: "Surprise", joy: "Happy", sadness: "Sad"
};

const urlParams = new URLSearchParams(window.location.search);
let authToken = urlParams.get('token');
if (authToken) {
    localStorage.setItem('sow_auth_token', authToken);
} else {
    authToken = localStorage.getItem('sow_auth_token') || '';
}

async function authFetch(url, options = {}) {
    options = { ...options };
    if (options.headers instanceof Headers) {
        if (authToken) options.headers.append('X-SOW-Token', authToken);
    } else {
        options.headers = { ...options.headers };
        if (authToken) options.headers['X-SOW-Token'] = authToken;
    }
    return fetch(url, options);
}

function withToken(url) {
    return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(authToken);
}

const settings = Object.assign({
    accent: 'blue',
    accentCustom: '#4BB8FF',
    oled: false,
    fontScale: 100,
    sound: true,
    tts: true,
    avatars: true,
    timestamps: true,
    dim: 72,
    chatWidth: 100,
    stageHeight: 30,
    reduceMotion: false,
    stageCollapsed: false,
}, JSON.parse(localStorage.getItem('sow_web_settings') || '{}'));

function saveSettings() {
    localStorage.setItem('sow_web_settings', JSON.stringify(settings));
}

function hexToRgb(hex) {
    const m = hex.replace('#', '');
    const v = m.length === 3 ? m.split('').map(c => c + c).join('') : m;
    const n = parseInt(v, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function applySettings() {
    const root = document.documentElement;
    root.dataset.accent = settings.accent;
    if (settings.accent === 'custom') {
        const [r, g, b] = hexToRgb(settings.accentCustom);
        root.style.setProperty('--accent', settings.accentCustom);
        root.style.setProperty('--accent-soft', `rgba(${r},${g},${b},.14)`);
        root.style.setProperty('--accent-border', `rgba(${r},${g},${b},.45)`);
        root.style.setProperty('--accent-text', settings.accentCustom);
        root.style.setProperty('--user-bubble',
            `linear-gradient(135deg, rgba(${r},${g},${b},.16), rgba(${r},${g},${b},.09))`);
    } else {
        root.style.removeProperty('--accent');
        root.style.removeProperty('--accent-soft');
        root.style.removeProperty('--accent-border');
        root.style.removeProperty('--accent-text');
        root.style.removeProperty('--user-bubble');
    }

    root.dataset.oled = settings.oled ? '1' : '0';
    root.style.setProperty('--font-scale', settings.fontScale / 100);
    root.style.setProperty('--bg-dim', settings.dim / 100);
    root.style.setProperty('--chat-width', settings.chatWidth / 100);
    root.style.setProperty('--stage-h', settings.stageHeight + 'vh');

    document.body.classList.toggle('no-avatars', !settings.avatars);
    document.body.classList.toggle('no-timestamps', !settings.timestamps);
    document.body.classList.toggle('reduce-motion', settings.reduceMotion);
    document.body.classList.toggle('stage-collapsed', settings.stageCollapsed);

    const $ = id => document.getElementById(id);
    if ($('font-scale')) $('font-scale').value = settings.fontScale;
    if ($('dim-range')) $('dim-range').value = settings.dim;
    if ($('chatwidth-range')) $('chatwidth-range').value = settings.chatWidth;
    if ($('stageheight-range')) $('stageheight-range').value = settings.stageHeight;
    if ($('sound-toggle')) $('sound-toggle').checked = settings.sound;
    if ($('tts-toggle')) $('tts-toggle').checked = settings.tts;
    if ($('avatars-toggle')) $('avatars-toggle').checked = settings.avatars;
    if ($('timestamps-toggle')) $('timestamps-toggle').checked = settings.timestamps;
    if ($('motion-toggle')) $('motion-toggle').checked = settings.reduceMotion;
    if ($('oled-toggle')) $('oled-toggle').checked = settings.oled;
    if ($('collapse-stage-toggle')) $('collapse-stage-toggle').checked = settings.stageCollapsed;
    if ($('accent-custom')) $('accent-custom').value = settings.accentCustom;
    document.querySelectorAll('.accent-swatch').forEach(s => {
        s.classList.toggle('selected', s.dataset.accent === settings.accent);
    });
}

function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

let audioCtx = null;
function playPop(forUser = false) {
    if (!settings.sound) return;
    try {
        audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(forUser ? 620 : 880, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(forUser ? 440 : 1180, audioCtx.currentTime + 0.08);
        gain.gain.setValueAtTime(0.06, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.16);
        osc.connect(gain).connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + 0.18);
    } catch (e) { /* audio not available */ }
}

function showToast(text, ms = 2600) {
    const c = document.getElementById('toast-container');
    if (!c) return;
    const t = document.createElement('div');
    t.className = 'toast';
    t.textContent = text;
    c.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, ms - 300);
    setTimeout(() => t.remove(), ms);
}

let audioQueue = [];
let isPlayingAudio = false;
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

const chatContainer      = document.getElementById('chat-container');
const charAvatarElement  = document.getElementById('char-avatar');
const statusTextElement  = document.getElementById('status-text');
const typingIndicator    = document.getElementById('typing-indicator');
const msgInput           = document.getElementById('msg-input');
const sendBtn            = document.getElementById('send-btn');
const stopBtn            = document.getElementById('stop-btn');
const micBtn             = document.getElementById('mic-btn');
const menuBtn            = document.getElementById('menu-btn');
const characterGrid      = document.getElementById('character-grid');
const chatsList          = document.getElementById('chats-list');
const variablesBar       = document.getElementById('variables-bar');
const scrollBottomBtn    = document.getElementById('scroll-bottom-btn');
const drawerOverlay      = document.getElementById('drawer-overlay');
const avatarContainer    = document.getElementById('avatar-container');
const avatarCanvas       = document.getElementById('avatar-canvas');
const avatarImage        = document.getElementById('avatar-image');
const stageToggleFab     = document.getElementById('stage-fab');
const stagePanel         = document.getElementById('stage-panel');
const stageCollapseBtn   = document.getElementById('stage-collapse-btn');
const charNameElement    = document.getElementById('char-name');

function openDrawer(id) {
    closeDrawers();
    const d = document.getElementById(id);
    if (d) d.classList.add('open');
    drawerOverlay.classList.remove('hidden');
}
function closeDrawers() {
    document.querySelectorAll('.drawer').forEach(d => d.classList.remove('open'));
    drawerOverlay.classList.add('hidden');
}
drawerOverlay.addEventListener('click', closeDrawers);
document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', closeDrawers);
});

let currentAvatarMode = "Nothing";

// Live2D
let pixiApp = null;
let currentLive2dModel = null;
let l2dMouthVolume = 0;

// VRM
let threeScene = null;
let threeRenderer = null;
let threeCamera = null;
let currentVrm = null;
let currentMixer = null;
let clock = null;
let lookAtTarget = null;
let targetMouseX = 0;
let targetMouseY = 0;
let jitterX = 0;
let jitterY = 0;
let idleExpressionTime = 0;
let orbitControls = null;
let vrmAnimateRunning = false;
let vrmIdleAction = null;
let vrmCurrentAction = null;
let vrmEmotionBusyUntil = 0;
let vrmLoadToken = 0;
const vrmClipCache = new Map();
let resizeObserver = null;

function teardownStage() {
    if (pixiApp) {
        try { pixiApp.destroy(true, { children: true, texture: true, baseTexture: true }); } catch (e) {}
        pixiApp = null;
    }
    currentLive2dModel = null;
    l2dMouthVolume = 0;

    vrmAnimateRunning = false;
    vrmIdleAction = null;
    vrmCurrentAction = null;
    if (threeRenderer) {
        try { threeRenderer.dispose(); } catch (e) {}
    }
    threeRenderer = null;
    threeScene = null;
    threeCamera = null;
    currentVrm = null;
    currentMixer = null;
    clock = null;
    orbitControls = null;
    vrmClipCache.clear();

    if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null; }

    avatarContainer?.classList.add('hidden');
    avatarCanvas?.classList.add('hidden');
    avatarImage?.classList.add('hidden');
    stageToggleFab?.classList.add('hidden');
    stagePanel?.classList.add('hidden');
}

function watchStageResize(targetEl, onResize) {
    if (!targetEl || !window.ResizeObserver) return;
    resizeObserver = new ResizeObserver(() => onResize());
    resizeObserver.observe(targetEl);
}

async function loadAvatar(charName) {
    if (!charName || charName === "None") return;
    teardownStage();
    try {
        const resp = await authFetch(`/api/avatar_config/${encodeURIComponent(charName)}`);
        avatarConfig = await resp.json();
        currentAvatarMode = avatarConfig.mode || "Nothing";

        if (currentAvatarMode === "Live2D Model") {
            avatarContainer.classList.remove('hidden');
            avatarCanvas.classList.remove('hidden');
            await new Promise(resolve => requestAnimationFrame(resolve));
            await initLive2D(avatarCanvas, withToken('/api/l2d_model/' + encodeURIComponent(charName)));

        } else if (currentAvatarMode === "VRM" && avatarConfig.vrm_model_file) {
            avatarContainer.classList.remove('hidden');
            avatarCanvas.classList.remove('hidden');
            await new Promise(resolve => requestAnimationFrame(resolve));
            await initVRM(avatarCanvas, withToken(avatarConfig.vrm_model_file));

        } else if (currentAvatarMode === "Expressions Images" && avatarConfig.expression_images_folder) {
            showEmotionImage(currentEmotion() || 'neutral');
        }
    } catch (e) {
        console.error("Failed to load avatar config:", e);
    }
}

function currentEmotion() {
    return window.__lastWebEmotion || null;
}

// ── Live2D ────────────────────────────────────────────────────────
async function initLive2D(canvas, modelUrl) {
    const { Application } = PIXI;
    const { Live2DModel } = PIXI.live2d;

    window.PIXI = PIXI;

    pixiApp = new Application({
        view: canvas,
        backgroundAlpha: 0,
        autoStart: true,
        resizeTo: canvas.parentElement,
        antialias: true,
        autoDensity: true,
        resolution: window.devicePixelRatio || 2,
    });

    try {
        currentLive2dModel = await Live2DModel.from(modelUrl);
        pixiApp.stage.addChild(currentLive2dModel);

        pixiApp.resize();
        
        fitLive2D();
        enableLive2DDragAndScale(canvas, currentLive2dModel);
        attachL2DLipSync(currentLive2dModel);

        pixiApp.ticker.add(() => {
            l2dMouthVolume *= 0.90;
            if (l2dMouthVolume < 0.01) l2dMouthVolume = 0;
        });

        stageToggleFab?.classList.remove('hidden');
        renderStagePanel();

        watchStageResize(canvas.parentElement, () => {
            if (!pixiApp || !currentLive2dModel) return;
            pixiApp.resize();
            fitLive2D();
        });
    } catch (e) {
        console.error("Live2D Load Error:", e);
        showToast("Live2D model failed to load");
    }
}

function fitLive2D() {
    if (!pixiApp || !currentLive2dModel) return;
    const m = currentLive2dModel;
    const zoom = m.__zoom ?? 1;

    m.scale.set(1);
    const bw = Math.max(1, m.width);
    const bh = Math.max(1, m.height);
    const base = Math.min(pixiApp.renderer.width / bw, pixiApp.renderer.height / bh);
    if (!isFinite(base) || base <= 0) return;

    m.__baseScale = base;
    m.scale.set(base * zoom);
    m.anchor.set(0.5, 0.5);
    m.position.set(pixiApp.renderer.width / 2, pixiApp.renderer.height / 2);
}

function attachL2DLipSync(model) {
    const im = model.internalModel;
    if (!im || im.__lipsyncHooked) return;
    im.__lipsyncHooked = true;
    const apply = () => {
        if (l2dMouthVolume <= 0.01) return;
        try {
            im.coreModel.setParameterValueById("ParamMouthOpenY", Math.min(1, l2dMouthVolume));
        } catch (e) { /* param missing on this model */ }
    };
    if (typeof im.on === 'function') {
        im.on('beforeModelUpdate', apply);
    }
}

function enableLive2DDragAndScale(canvas, model) {
    if (!model) return;

    canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.05 : 0.95;
        const zoom = Math.max(0.2, Math.min(4.0, (model.__zoom ?? 1) * factor));
        model.__zoom = zoom;
        if (model.__baseScale) model.scale.set(model.__baseScale * zoom);
    }, { passive: false });

    model.interactive = true;
    let isDragging = false;
    let dragData = null;
    let lastPosition = { x: 0, y: 0 };

    model.on('pointerdown', (event) => {
        isDragging = true;
        dragData = event.data;
        const localPos = dragData.getLocalPosition(model.parent);
        lastPosition = {
            x: localPos.x - model.position.x,
            y: localPos.y - model.position.y
        };
    });

    model.on('pointermove', () => {
        if (isDragging && dragData) {
            const newPos = dragData.getLocalPosition(model.parent);
            model.position.set(
                newPos.x - lastPosition.x,
                newPos.y - lastPosition.y
            );
        }
    });

    const stopDragging = () => { isDragging = false; dragData = null; };
    model.on('pointerup', stopDragging);
    model.on('pointerupoutside', stopDragging);
}

// ── VRM ───────────────────────────────────────────────────────────
async function initVRM(canvas, modelUrl) {
    const THREE                                 = await import('three');
    const { GLTFLoader }                        = await import('three/addons/loaders/GLTFLoader.js');
    const { OrbitControls }                     = await import('three/addons/controls/OrbitControls.js');
    const { VRMLoaderPlugin, VRMUtils, VRMLookAt } = await import('@pixiv/three-vrm');

    const container = canvas.parentElement;
    const W = container.clientWidth  || 400;
    const H = container.clientHeight || 600;

    threeRenderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    threeRenderer.setSize(W, H);
    threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    if ('outputColorSpace' in threeRenderer && THREE.SRGBColorSpace) {
        threeRenderer.outputColorSpace = THREE.SRGBColorSpace;
    }
    threeRenderer.shadowMap.enabled = true;

    threeCamera = new THREE.PerspectiveCamera(30.0, W / H, 0.1, 20.0);
    threeCamera.position.set(0.0, 1.4, 2.0);

    threeScene = new THREE.Scene();

    threeScene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const directionalLight = new THREE.DirectionalLight(0xffffff, Math.PI);
    directionalLight.position.set(1.0, 1.0, 1.0).normalize();
    threeScene.add(directionalLight);

    lookAtTarget = new THREE.Object3D();
    threeCamera.add(lookAtTarget);
    threeScene.add(threeCamera);

    orbitControls = new OrbitControls(threeCamera, threeRenderer.domElement);
    orbitControls.screenSpacePanning = true;
    orbitControls.target.set(0.0, 1.0, 0.0);
    orbitControls.update();

    function installSmoothLookAt(vrm) {
        try {
            class VRMSmoothLookAt extends VRMLookAt {
                constructor(humanoid, applier) {
                    super(humanoid, applier);
                    this.smoothFactor = 10.0;
                    this.yawLimit   = 45.0;
                    this.pitchLimit = 45.0;
                    this._yawDamped   = 0.0;
                    this._pitchDamped = 0.0;
                    this._v3A         = new THREE.Vector3();
                }
                update(delta) {
                    if (this.target && this.autoUpdate) {
                        this.lookAt(this.target.getWorldPosition(this._v3A));
                        if (Math.abs(this._yaw) > this.yawLimit ||
                            Math.abs(this._pitch) > this.pitchLimit) {
                            this._yaw = 0.0; this._pitch = 0.0;
                        }
                        const k = 1.0 - Math.exp(-this.smoothFactor * delta);
                        this._yawDamped   += (this._yaw   - this._yawDamped)   * k;
                        this._pitchDamped += (this._pitch - this._pitchDamped) * k;
                        this.applier.applyYawPitch(this._yawDamped, this._pitchDamped);
                        this._needsUpdate = false;
                    }
                    if (this._needsUpdate) {
                        this._needsUpdate = false;
                        this.applier.applyYawPitch(this._yaw, this._pitch);
                    }
                }
            }
            const smooth = new VRMSmoothLookAt(vrm.humanoid, vrm.lookAt.applier);
            smooth.copy(vrm.lookAt);
            vrm.lookAt = smooth;
        } catch (e) {
            console.warn("[VRM] smooth look-at unavailable, using default:", e);
        }
        vrm.lookAt.target = threeCamera;
    }

    const loader = new GLTFLoader();
    loader.register(parser => new VRMLoaderPlugin(parser));

    loader.load(
        modelUrl,
        (gltf) => {
            currentVrm = gltf.userData.vrm;

            VRMUtils.removeUnnecessaryVertices(gltf.scene);
            VRMUtils.combineSkeletons(gltf.scene);
            VRMUtils.combineMorphs(currentVrm);

            gltf.scene.traverse(obj => {
                obj.frustumCulled = false;
            });

            installSmoothLookAt(currentVrm);
            threeScene.add(currentVrm.scene);
            VRMUtils.rotateVRM0(currentVrm);

            currentMixer = new THREE.AnimationMixer(currentVrm.scene);

            loadVrmAnimation(withToken('/vrm/expressions/neutral.fbx'), true)
                .then(() => renderStagePanel())
                .catch(e => console.warn("[VRM] idle animation skipped:", e));

            startBlinking();
            console.log("[VRM] Model loaded successfully");

            watchStageResize(container, () => {
                if (!threeRenderer || !threeCamera) return;
                const nW = container.clientWidth;
                const nH = container.clientHeight;
                if (!nW || !nH) return;
                threeCamera.aspect = nW / nH;
                threeCamera.updateProjectionMatrix();
                threeRenderer.setSize(nW, nH);
            });
            stageToggleFab?.classList.remove('hidden');
        },
        (progress) => {
            if (progress.total > 0) {
                const pct = Math.round(progress.loaded / progress.total * 100);
                console.log(`[VRM] Loading model… ${pct}%`);
            }
        },
        (error) => {
            console.error("[VRM] Load error:", error);
            showToast("VRM model failed to load");
        }
    );

    document.addEventListener('mousemove', (e) => {
        targetMouseX =  (e.clientX / window.innerWidth)  * 2 - 1;
        targetMouseY = -(e.clientY / window.innerHeight) * 2 + 1;
    });

    function startBlinking() {
        if (!currentVrm || !currentVrm.expressionManager) return;
        const delay = 2000 + Math.random() * 6000;
        setTimeout(() => {
            if (!currentVrm || !currentVrm.expressionManager) return;
            const duration = 80 + Math.random() * 120;
            currentVrm.expressionManager.setValue('blink', 1.0);
            setTimeout(() => {
                if (currentVrm && currentVrm.expressionManager) {
                    currentVrm.expressionManager.setValue('blink', 0.0);
                }
            }, duration);
            startBlinking();
        }, delay);
    }

    clock = new THREE.Clock();
    vrmAnimateRunning = true;

    (function animate() {
        if (!vrmAnimateRunning || !threeRenderer || !threeScene) return;
        requestAnimationFrame(animate);

        const delta = clock.getDelta();

        updateIdleJitter(delta);

        if (lookAtTarget) {
            const time = clock.elapsedTime;
            const breathOffset = Math.sin(time * 1.5) * 0.05;
            const finalTargetX = targetMouseX * 3.0 + jitterX;
            const finalTargetY = targetMouseY * 2.0 + jitterY + breathOffset;
            lookAtTarget.position.x += (finalTargetX - lookAtTarget.position.x) * 5.0 * delta;
            lookAtTarget.position.y += (finalTargetY - lookAtTarget.position.y) * 5.0 * delta;
            lookAtTarget.position.z  = -5.0;
        }

        if (currentMixer) currentMixer.update(delta);
        if (currentVrm)   currentVrm.update(delta);
        if (orbitControls) orbitControls.update();

        threeRenderer.render(threeScene, threeCamera);
    })();
}

function updateIdleJitter(deltaTime) {
    if (performance.now() < vrmEmotionBusyUntil) return;

    idleExpressionTime -= deltaTime;
    if (idleExpressionTime <= 0) {
        idleExpressionTime = 2.0 + Math.random() * 3.0;
        if (Math.random() > 0.4) {
            jitterX = (Math.random() - 0.5) * 1.5;
            jitterY = (Math.random() - 0.5) * 1.0;
        } else {
            jitterX = 0;
            jitterY = 0;
        }
        if (currentVrm && currentVrm.expressionManager) {
            const rand = Math.random();
            currentVrm.expressionManager.setValue('relaxed',  0);
            currentVrm.expressionManager.setValue('surprised', 0);
            if (rand < 0.3) {
                currentVrm.expressionManager.setValue('relaxed', 0.10 + Math.random() * 0.1);
            } else if (rand > 0.9) {
                currentVrm.expressionManager.setValue('surprised', 0.05 + Math.random() * 0.08);
            }
        }
    }
}

async function loadVrmAnimation(url, isIdle = false) {
    const THREE = await import('three');
    if (!currentVrm || !currentMixer) throw new Error("VRM not ready");

    let clip = vrmClipCache.get(url);
    if (!clip) {
        const { loadMixamoAnimation } = await import('loadMixamo');
        clip = await loadMixamoAnimation(url, currentVrm);
        vrmClipCache.set(url, clip);
    }

    const action = currentMixer.clipAction(clip);
    action.reset();
    if (isIdle) {
        action.loop = THREE.LoopRepeat;
        action.clampWhenFinished = false;
        vrmIdleAction = action;
    } else {
        action.loop = THREE.LoopOnce;
        action.clampWhenFinished = true;
    }

    if (vrmCurrentAction && vrmCurrentAction !== action) {
        action.crossFadeFrom(vrmCurrentAction, 0.3, true);
    }
    action.play();
    vrmCurrentAction = action;

    if (!isIdle) {
        const myToken = ++vrmLoadToken;
        vrmEmotionBusyUntil = performance.now() + 15000;
        const onFinish = () => {
            if (myToken !== vrmLoadToken) return;
            vrmEmotionBusyUntil = 0;
            if (vrmIdleAction && vrmCurrentAction && vrmCurrentAction !== vrmIdleAction) {
                try {
                    vrmCurrentAction.crossFadeTo(vrmIdleAction, 0.3, true);
                    vrmIdleAction.reset().play();
                } catch (e) {
                    vrmIdleAction.reset().play();
                }
                vrmCurrentAction = vrmIdleAction;
            }
            currentMixer.removeEventListener('finished', onFinish);
        };
        currentMixer.addEventListener('finished', onFinish);
    }
    return action;
}

// ── Expression images mode ────────────────────────────────────────
function showEmotionImage(emotion) {
    if (!avatarConfig.expression_images_folder) return;
    const folder = avatarConfig.expression_images_folder.replace(/\/$/, '');
    const candidates = [
        `${folder}/${emotion}.gif`, `${folder}/${emotion}.png`,
        `${folder}/neutral.gif`,    `${folder}/neutral.png`,
    ];
    avatarContainer.classList.remove('hidden');
    avatarImage.classList.remove('hidden');
    stageToggleFab?.classList.remove('hidden');
    const exprWrap = document.getElementById('panel-expressions');
    if (exprWrap && !exprWrap.childElementCount) renderStagePanel();
    const tryLoad = (i) => {
        if (i >= candidates.length) return;
        avatarImage.src = withToken(candidates[i]);
        avatarImage.onerror = () => tryLoad(i + 1);
    };
    tryLoad(0);
}

// ── Stage control panel (expressions / animations) ───────────────
if (stageToggleFab && stagePanel) {
    stageToggleFab.onclick = (e) => {
        e.stopPropagation();
        stagePanel.classList.toggle('hidden');
    };
}
document.getElementById('stage-panel-close')?.addEventListener('click', () => {
    stagePanel?.classList.add('hidden');
});
if (stageCollapseBtn) {
    stageCollapseBtn.onclick = () => {
        settings.stageCollapsed = !settings.stageCollapsed;
        saveSettings();
        applySettings();
        setTimeout(() => {
            if (pixiApp) { pixiApp.resize(); fitLive2D(); }
        }, 60);
    };
}

function markActiveChip(containerId, matchFn) {
    const c = document.getElementById(containerId);
    if (!c) return;
    c.querySelectorAll('.l2d-btn').forEach(b =>
        b.classList.toggle('active', !!matchFn(b)));
}

function renderStagePanel() {
    const exprWrap = document.getElementById('panel-expressions');
    const animWrap = document.getElementById('panel-animations');
    const exprSection = document.getElementById('section-expressions');
    const animSection = document.getElementById('section-animations');
    if (!exprWrap || !animWrap) return;
    exprWrap.innerHTML = '';
    animWrap.innerHTML = '';

    if (currentAvatarMode === "Live2D Model" && currentLive2dModel) {
        exprSection?.classList.remove('hidden');
        animSection?.classList.remove('hidden');
        renderLive2DExpressions(exprWrap);
        renderLive2DMotions(animWrap);
    } else if (currentAvatarMode === "VRM" && currentVrm) {
        exprSection?.classList.remove('hidden');
        animSection?.classList.remove('hidden');
        renderVrmExpressions(exprWrap);
        renderVrmAnimations(animWrap);
    } else if (currentAvatarMode === "Expressions Images") {
        exprSection?.classList.remove('hidden');
        animSection?.classList.add('hidden');
        renderImageEmotions(exprWrap);
    } else {
        exprSection?.classList.add('hidden');
        animSection?.classList.add('hidden');
    }
}

function makeChip(label, onClick, title) {
    const btn = document.createElement('button');
    btn.className = 'l2d-btn';
    btn.textContent = label;
    if (title) btn.title = title;
    btn.onclick = onClick;
    return btn;
}

function renderLive2DExpressions(wrap) {
    const model = currentLive2dModel;
    let list = [];
    try { list = model.internalModel.settings.expressions || []; } catch (e) {}
    const names = list.map(e => e?.name || e?.Name).filter(Boolean);

    if (!names.length) {
        wrap.innerHTML = '<span class="panel-empty">No expressions in this model</span>';
        return;
    }
    names.forEach(name => {
        wrap.appendChild(makeChip(name, () => {
            const ok = setLive2DExpression(model, name);
            if (!ok) showToast(`Expression "${name}" failed`);
            else {
                markActiveChip('panel-expressions', b => b.textContent === name);
                window.__lastWebEmotion = name.toLowerCase();
            }
        }));
    });
}

function renderLive2DMotions(wrap) {
    const model = currentLive2dModel;
    let motions = {};
    try { motions = model.internalModel.settings.motions || {}; } catch (e) {}

    const groups = Object.keys(motions || {}).filter(g => (motions[g] || []).length);
    if (!groups.length) {
        wrap.innerHTML = '<span class="panel-empty">No animations found</span>';
        return;
    }
    groups.forEach(group => {
        const head = document.createElement('div');
        head.className = 'chip-group-label';
        head.textContent = group;
        wrap.appendChild(head);

        const grid = document.createElement('div');
        grid.className = 'button-grid';
        const items = motions[group] || [];
        items.forEach((m, index) => {
            const file = m.file || m.File || "";
            const clean = file ? file.split('/').pop()
                .replace('.motion3.json', '').replace('.mtn', '') : `${group} [${index}]`;
            grid.appendChild(makeChip(clean, () => {
                try {
                    model.motion(group, index, 3);
                    markActiveChip('panel-animations', b => b.textContent === clean);
                } catch (e) { console.error("Motion error:", e); }
            }, `${group} · ${clean}`));
        });
        wrap.appendChild(grid);
    });
}

function vrmAvailablePresets() {
    const em = currentVrm?.expressionManager;
    if (!em) return [];
    const out = [];
    ['neutral','happy','angry','sad','relaxed','surprised'].forEach(p => {
        try { if (em.getExpression?.(p) || em.expressions?.has?.(p)) out.push(p); } catch (e) {}
    });
    return out.length ? out : ['neutral'];
}

function renderVrmExpressions(wrap) {
    const presets = vrmAvailablePresets();
    presets.forEach(p => {
        wrap.appendChild(makeChip(p, () => {
            setVrmExpression(p);
            markActiveChip('panel-expressions', b => b.textContent === p);
        }));
    });
}

function renderVrmAnimations(wrap) {
    const grid = document.createElement('div');
    grid.className = 'button-grid';
    grid.id = 'panel-animations-grid';
    STANDARD_EMOTIONS.forEach(emo => {
        grid.appendChild(makeChip(emo, async () => {
            try {
                await loadVrmAnimation(withToken(`/vrm/expressions/${emo}.fbx`), false);
                setVrmPresetForEmotion(emo);
                markActiveChip('panel-animations', b => b.textContent === emo);
            } catch (e) {
                console.warn("[VRM] animation failed:", emo, e);
                showToast(`No animation for "${emo}"`);
            }
        }));
    });
    wrap.appendChild(grid);
}

function renderImageEmotions(wrap) {
    STANDARD_EMOTIONS.forEach(emo => {
        wrap.appendChild(makeChip(emo, () => {
            window.__lastWebEmotion = emo;
            showEmotionImage(emo);
            markActiveChip('panel-expressions', b => b.textContent === emo);
        }));
    });
}

const EMOTION_SYNONYMS = {
    joy: ["joy","happy","smile","fun","laugh","happiness","cheer","delight"],
    amusement: ["amuse","happy","smile","laugh","fun"],
    love: ["love","heart","affection","blush"],
    admiration: ["admire","happy","smile","wow"],
    approval: ["approve","happy","nod"],
    caring: ["care","kind","warm","gentle"],
    gratitude: ["gratitude","thank","happy"],
    pride: ["pride","proud","confident","smug"],
    optimism: ["optimism","hope","smile","happy"],
    excitement: ["excite","excited","wow","surprise","energy"],
    desire: ["desire","want","lust","love"],
    anger: ["anger","angry","mad","rage","irritat","annoy"],
    annoyance: ["annoy","anger","angry","mad","irritat"],
    disapproval: ["disapprov","angry","frown","serious"],
    disgust: ["disgust","gross","ew"],
    disappointment: ["disappoint","sad","frown","upset"],
    sadness: ["sad","sorrow","cry","tears","gloom","melanchol"],
    grief: ["grief","sad","cry","tears","sorrow"],
    remorse: ["remorse","guilt","sad","sorry"],
    embarrassment: ["embarrass","blush","shame","shy"],
    nervousness: ["nervous","anxious","worry","sweat"],
    fear: ["fear","afraid","scared","terror","panic"],
    surprise: ["surprise","shock","wow","gasp"],
    realization: ["realiz","surprise","idea","notice"],
    confusion: ["confus","puzzl","question","wonder"],
    curiosity: ["curios","wonder","interest","question"],
    relief: ["relief","relax","calm","sigh"],
    neutral: ["neutral","idle","default","normal","calm","rest"],
};

function _norm(s) { return String(s || "").toLowerCase().replace(/[\s_\-.]/g, ""); }

function _matchLive2DExpression(model, emotion) {
    let list = [];
    try { list = model?.internalModel?.settings?.expressions || []; } catch (e) {}
    const names = list.map(e => e?.name || e?.Name || "").filter(Boolean);
    if (!names.length) return null;

    const emo = _norm(emotion);
    const syn = EMOTION_SYNONYMS[emotion] || [emo];

    for (const n of names) if (_norm(n) === emo) return n;
    for (const n of names) {
        const nn = _norm(n);
        if (nn.includes(emo) || emo.includes(nn)) return n;
    }
    for (const n of names) {
        const nn = _norm(n);
        for (const s of syn) {
            const ss = _norm(s);
            if (ss && (nn.includes(ss) || ss.includes(nn))) return n;
        }
    }
    return null;
}

function setLive2DExpression(model, name) {
    if (!model || !name) return false;
    let ok = false;
    try { model.expression(name); ok = true; } catch (e) { /* try deeper */ }
    try {
        const em = model.internalModel?.motionManager?.expressionManager;
        if (em && em.setExpression) { em.setExpression(name); ok = true; }
    } catch (e) { /* ignore */ }
    try {
        const em2 = model.internalModel?.expressionManager;
        if (em2 && em2.setExpression) { em2.setExpression(name); ok = true; }
    } catch (e) { /* ignore */ }
    return ok;
}

function resolveMotionGroup(emotion) {
    const groups = (() => {
        try { return Object.keys(currentLive2dModel?.internalModel?.settings?.motions || {}); }
        catch (e) { return []; }
    })();
    if (!groups.length) return null;

    let target = (avatarConfig.emotion_motions || {})[emotion];
    if (target === "none") return null;
    if (target && groups.includes(target)) return target;

    const syn = EMOTION_SYNONYMS[emotion] || [emotion];
    for (const g of groups) {
        if (_norm(g) === _norm(emotion)) return g;
        for (const s of syn) {
            const ss = _norm(s);
            if (ss && _norm(g).includes(ss)) return g;
        }
    }
    const fallback = DEFAULT_EMOTION_MOTIONS[emotion] || "Idle";
    for (const g of groups) {
        if (_norm(g) === _norm(fallback)) return g;
    }
    for (const f of ["Idle", "idle", "TapBody"]) {
        for (const g of groups) {
            if (_norm(g) === _norm(f)) return g;
        }
    }
    return groups[Math.floor(Math.random() * groups.length)];
}

function playLive2DEmotionMotion(emotion) {
    if (!currentLive2dModel) return;
    const group = resolveMotionGroup(emotion);
    if (!group) return;
    try {
        const items = currentLive2dModel.internalModel.settings.motions[group] || [];
        const index = items.length > 1 ? Math.floor(Math.random() * items.length) : 0;
        currentLive2dModel.motion(group, index, 3);
        console.log(`[Emotion] Live2D motion '${group}[${index}]' for '${emotion}'`);
    } catch (e) { console.warn("[Emotion] motion failed:", e); }
}

const VRM_EMOTION_PRESET = {
    anger: 'angry', disapproval: 'angry', annoyance: 'angry', disgust: 'angry',
    admiration: 'happy', amusement: 'happy', approval: 'happy', desire: 'happy',
    gratitude: 'happy', love: 'happy', optimism: 'happy', pride: 'happy', joy: 'happy',
    neutral: 'neutral',
    caring: 'relaxed', relief: 'relaxed',
    disappointment: 'sad', grief: 'sad', remorse: 'sad', sadness: 'sad',
    confusion: 'surprised', curiosity: 'surprised', embarrassment: 'surprised',
    fear: 'surprised', nervousness: 'surprised', realization: 'surprised',
    surprise: 'surprised', excitement: 'surprised',
};

function setVrmExpression(preset) {
    if (!currentVrm?.expressionManager) return;
    const em = currentVrm.expressionManager;
    ['neutral','happy','angry','sad','relaxed','surprised'].forEach(p => {
        try { em.setValue(p, 0); } catch (e) {}
    });
    try { em.setValue(preset, 1.0); } catch (e) {}
}

function setVrmPresetForEmotion(emotion) {
    const preset = VRM_EMOTION_PRESET[emotion] || 'neutral';
    setVrmExpression(preset);
}

function handleAvatarEmotion(emotion) {
    if (!emotion) return;
    window.__lastWebEmotion = emotion;

    if (currentLive2dModel) {
        let target = (avatarConfig.emotion_expressions || {})[emotion];
        if (!target || !setLive2DExpression(currentLive2dModel, target)) {
            target = _matchLive2DExpression(currentLive2dModel, emotion);
            if (target) setLive2DExpression(currentLive2dModel, target);
        }
        if (target) console.log(`[Emotion] Live2D expression '${target}' for '${emotion}'`);
        playLive2DEmotionMotion(emotion);
        markActiveChip('panel-expressions', b => b.textContent === target);

    } else if (currentVrm) {
        setVrmPresetForEmotion(emotion);
        vrmEmotionBusyUntil = performance.now() + 6000;
        loadVrmAnimation(withToken(`/vrm/expressions/${emotion}.fbx`), false)
            .catch(() => { /* model without this clip — expression still applied */ });
        console.log(`[Emotion] VRM '${emotion}'`);

    } else if (currentAvatarMode === "Expressions Images") {
        showEmotionImage(emotion);
    }
}

function handleAvatarTelemetry(volume) {
    if (currentLive2dModel) {
        l2dMouthVolume = Math.max(l2dMouthVolume, Number(volume) || 0);
    }
    if (currentVrm && currentVrm.expressionManager) {
        try { currentVrm.expressionManager.setValue('aa', volume); } catch (e) {}
    }
}

async function init() {
    marked.setOptions({ breaks: true, gfm: true });
    applySettings();

    try {
        const resp = await authFetch('/api/config');
        const config = await resp.json();
        userName = config.user_name || "User";
        currentChatId = config.chat_id || "default";

        await loadCharacters();
        await loadBackground();

        if (config.active_character && config.active_character !== "None") {
            currentCharacter = config.active_character;
            charNameElement.innerText = currentCharacter;
            charAvatarElement.src = withToken(`/api/avatar/${encodeURIComponent(currentCharacter)}`);
            statusTextElement.innerText = "Connecting to chat…";
            await loadAvatar(config.active_character);
            await Promise.all([loadHistory(true), loadChats(), loadVariables()]);
            connectWebSocket();
            setupIntersectionObserver();
        } else {
            statusTextElement.innerText = "Select a character";
            statusTextElement.className = "status-offline";
            charNameElement.innerText = "None";
            openDrawer('characters-drawer');
        }
    } catch (error) {
        console.error("Failed to load config:", error);
        statusTextElement.innerText = "Connection error";
        statusTextElement.className = "status-offline";
    }
}

let allCharacters = [];

async function loadCharacters() {
    try {
        const resp = await authFetch('/api/characters');
        const data = await resp.json();
        allCharacters = data.characters || [];
        renderCharacters();
    } catch (e) {
        console.error("Failed to load characters list", e);
    }
}

function renderCharacters(filter = "") {
    if (!characterGrid) return;
    characterGrid.innerHTML = "";
    const q = (filter || "").trim().toLowerCase();

    const list = allCharacters.filter(c =>
        !q || c.name.toLowerCase().includes(q) || (c.title || "").toLowerCase().includes(q)
    );

    if (!list.length) {
        characterGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--text-dim);padding:30px 10px;">
            ${allCharacters.length ? "Nothing found for this search." : "No characters yet.<br>Add them in the desktop app first."}</div>`;
        return;
    }

    list.forEach(char => {
        const card = document.createElement('div');
        card.className = 'char-card' + (char.name === currentCharacter ? ' active-char' : '');
        card.innerHTML = `
            <div class="card-avatar-wrap">
                <img class="card-avatar" src="${withToken('/api/avatar/' + encodeURIComponent(char.name))}" alt="" loading="lazy">
                ${char.name === currentCharacter ? '<span class="card-active-badge">Active</span>' : ''}
            </div>
            <h3 class="card-name">${escapeHtml(char.name)}</h3>
            ${char.title ? `<div class="card-title">${escapeHtml(char.title)}</div>` : ''}
            <div class="card-meta">${char.chat_count} chat${char.chat_count === 1 ? '' : 's'}</div>
        `;
        card.onclick = async () => {
            if (char.name === currentCharacter) { closeDrawers(); return; }
            statusTextElement.innerText = "Switching…";
            statusTextElement.className = "";
            closeDrawers();
            try {
                await authFetch('/api/character/switch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ character: char.name })
                });
            } catch (e) {
                console.error("Failed to switch character", e);
                statusTextElement.innerText = "Switch failed";
                statusTextElement.className = "status-offline";
            }
        };
        characterGrid.appendChild(card);
    });
}

const charSearch = document.getElementById('char-search');
if (charSearch) {
    charSearch.addEventListener('input', () => renderCharacters(charSearch.value));
}

async function loadChats() {
    if (!currentCharacter) return;
    try {
        const resp = await authFetch(`/api/chats/${encodeURIComponent(currentCharacter)}`);
        const data = await resp.json();
        chatsList.innerHTML = "";

        if (!data.chats.length) {
            chatsList.innerHTML = `<div style="text-align:center;color:var(--text-dim);padding:24px 8px;">No chats yet.</div>`;
            return;
        }

        data.chats.forEach(chat => {
            const item = document.createElement('div');
            item.className = 'chat-item' + (chat.is_current ? ' current' : '');
            item.innerHTML = `
                <div class="ci-top">
                    <span class="ci-name">${escapeHtml(chat.name)}</span>
                    ${chat.is_branch ? '<span class="ci-badge">branch</span>' : ''}
                </div>
                ${chat.last_message ? `<div class="ci-preview">${escapeHtml(chat.last_message)}</div>` : ''}
                <div class="ci-count">${chat.message_count} messages</div>
            `;
            item.onclick = () => switchChat(chat.id);
            chatsList.appendChild(item);
        });
    } catch (e) {
        console.error("Failed to load chats", e);
    }
}

async function switchChat(chatId) {
    if (chatId === currentChatId) { closeDrawers(); return; }
    closeDrawers();
    try {
        await authFetch('/api/chat/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: currentCharacter, chat_id: chatId })
        });
        currentChatId = chatId;
        historyOffset = 0;
        hasMoreHistory = true;
        chatContainer.innerHTML = "";
        await loadHistory(true);
        await loadChats();
        await loadVariables();
        showToast("Chat switched");
    } catch (e) {
        console.error("Failed to switch chat", e);
        showToast("Failed to switch chat");
    }
}

async function loadVariables() {
    if (!currentCharacter) return;
    try {
        const resp = await authFetch(`/api/variables/${encodeURIComponent(currentCharacter)}`);
        const data = await resp.json();
        variablesBar.innerHTML = "";

        if (!data.variables.length) {
            variablesBar.classList.add('hidden');
            return;
        }
        variablesBar.classList.remove('hidden');

        const ICONS = { heart: "❤️", shield: "🛡️", flask: "🧪", star: "⭐", coin: "🪙", sword: "⚔️", bag: "🎒" };
        data.variables.forEach(v => {
            const chip = document.createElement('div');
            chip.className = 'var-chip';
            chip.id = `var-${v.id}`;
            let valueHtml;
            if (v.type === 'int' && v.max) {
                valueHtml = `<span class="var-value">${escapeHtml(String(v.value))}/${escapeHtml(String(v.max))}</span>`;
            } else if (v.type === 'bool') {
                valueHtml = `<span class="var-value">${v.value ? 'Yes' : 'No'}</span>`;
            } else {
                valueHtml = `<span class="var-value">${escapeHtml(String(v.value ?? ''))}</span>`;
            }
            chip.innerHTML = `
                <span class="var-icon">${ICONS[v.icon] || escapeHtml(v.icon) || '•'}</span>
                <span class="var-name">${escapeHtml(v.name)}</span>
                ${valueHtml}
            `;
            variablesBar.appendChild(chip);
        });
    } catch (e) {
        console.error("Failed to load variables", e);
    }
}

function bumpVariableChips() {
    variablesBar.querySelectorAll('.var-chip').forEach(c => {
        c.classList.add('bumped');
        setTimeout(() => c.classList.remove('bumped'), 700);
    });
}

async function loadBackground() {
    try {
        const resp = await authFetch('/api/background');
        if (resp.ok) {
            document.body.style.backgroundImage =
                `url('${withToken('/api/background')}')`;
        }
    } catch (e) { /* no custom background */ }
}

function setupIntersectionObserver() {
    chatContainer.addEventListener('scroll', async () => {
        if (chatContainer.scrollTop <= 50 && !isLoadingHistory && hasMoreHistory) {
            const oldScrollHeight = chatContainer.scrollHeight;
            await loadHistory(false);
            chatContainer.scrollTop = chatContainer.scrollHeight - oldScrollHeight;
        }

        const far = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight > 260;
        scrollBottomBtn.classList.toggle('hidden', !far);
    });
}

function formatTime(iso) {
    if (!iso) return "";
    try {
        const d = new Date(iso);
        if (isNaN(d)) return "";
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) { return ""; }
}

async function loadHistory(isFirstLoad = false) {
    if (!currentCharacter || isLoadingHistory || !hasMoreHistory) return;
    isLoadingHistory = true;
    try {
        const resp = await authFetch(
            `/api/history/${encodeURIComponent(currentCharacter)}?offset=${historyOffset}&limit=${HISTORY_LIMIT}`
        );
        const data = await resp.json();
        if (data.history && data.history.length > 0) {
            const frag = document.createDocumentFragment();
            data.history.forEach(msg => {
                const el = createMessageElement(msg.text, msg.is_user ? 'user' : 'waifu', msg.id, msg);
                frag.appendChild(el);
            });
            if (isFirstLoad) {
                chatContainer.innerHTML = "";
                chatContainer.appendChild(frag);
                scrollToBottom(true);
            } else {
                chatContainer.insertBefore(frag, chatContainer.firstChild);
            }
            historyOffset += data.history.length;
            if (data.history.length < HISTORY_LIMIT) hasMoreHistory = false;
        } else {
            hasMoreHistory = false;
        }
    } catch (error) {
        console.error("Failed to load history:", error);
    }
    isLoadingHistory = false;
}

function connectWebSocket() {
    clearTimeout(wsReconnectTimer);

    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        return;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(authToken)}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("WebSocket connected");
        wsReconnectDelay = 2000;
        statusTextElement.innerText  = "Online";
        statusTextElement.className  = "status-online";
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            switch (data.type) {
                case "chunk":            handleIncomingChunk(data.text); break;
                case "message_start":
                    showTypingIndicator();
                    currentMessageId = Date.now().toString();
                    currentMessageDiv = null;
                    break;
                case "message_end":
                    hideTypingIndicator();
                    currentMessageId = null; currentMessageDiv = null;
                    playPop(false);
                    loadVariables();
                    loadChats();
                    bumpVariableChips();
                    if (pendingRegenReload) {
                        pendingRegenReload = false;
                        historyOffset = 0; hasMoreHistory = true;
                        chatContainer.innerHTML = "";
                        loadHistory(true);
                    }
                    break;
                case "user_message":     {
                    onBroadcastUserMessage(data.text);
                    break;
                }
                case "character_changed": location.reload(); break;
                case "chat_switched": {
                    if (data.character === currentCharacter) {
                        historyOffset = 0; hasMoreHistory = true;
                        chatContainer.innerHTML = "";
                        loadHistory(true); loadChats(); loadVariables();
                    }
                    break;
                }
                case "message_deleted":  {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (el) el.remove();
                    break;
                }
                case "message_edited":   {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (el) {
                        el.dataset.rawText = data.text;
                        const c = el.querySelector('.msg-content');
                        if (c) c.innerHTML = marked.parse(data.text);
                    }
                    break;
                }
                case "message_variant_changed": {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (el) {
                        el.dataset.rawText = data.text;
                        const c = el.querySelector('.msg-content');
                        if (c) c.innerHTML = marked.parse(data.text);
                        const bar = el.querySelector('.msg-variants');
                        if (bar) {
                            bar.dataset.count = data.total;
                            bar.dataset.index = data.current - 1;
                            if (data.total > 1) bar.classList.add('has-variants');
                            const counter = bar.querySelector('.variant-counter');
                            if (counter) {
                                counter.textContent = `${data.current}/${data.total}`;
                                counter.title = `Response ${data.current} of ${data.total}`;
                            }
                        }
                    }
                    break;
                }
                case "regenerate_start": {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (el) {
                        currentMessageDiv = el;
                        currentMessageId = data.id;
                        el.dataset.rawText = "";
                        const c = el.querySelector('.msg-content');
                        if (c) c.innerHTML = "";
                    }
                    showTypingIndicator();
                    pendingRegenReload = false;
                    break;
                }
                case "regenerate_chunk": {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (!el) break;
                    hideTypingIndicator();
                    if (currentMessageDiv !== el) {
                        currentMessageDiv = el;
                        currentMessageId = data.id;
                    }
                    el.dataset.rawText = data.text;
                    const c = el.querySelector('.msg-content');
                    if (c) c.innerHTML = marked.parse(data.text);
                    scrollToBottom();
                    break;
                }
                case "regenerate_end": {
                    const el = document.getElementById(`msg-${data.id}`);
                    if (el) {
                        el.dataset.rawText = data.text;
                        const c = el.querySelector('.msg-content');
                        if (c) c.innerHTML = marked.parse(data.text);
                        if (data.total) {
                            const bar = el.querySelector('.msg-variants');
                            if (bar) {
                                bar.dataset.count = data.total;
                                bar.dataset.index = (data.current || 1) - 1;
                                if (data.total > 1) bar.classList.add('has-variants');
                                const counter = bar.querySelector('.variant-counter');
                                if (counter) {
                                    counter.textContent = `${data.current}/${data.total}`;
                                    counter.title = `Response ${data.current} of ${data.total}`;
                                }
                            }
                        }
                    }
                    hideTypingIndicator();
                    currentMessageDiv = null;
                    currentMessageId = null;
                    pendingRegenReload = false;
                    playPop(false);
                    loadVariables();
                    loadChats();
                    bumpVariableChips();
                    break;
                }
                case "audio":            if (settings.tts) handleIncomingAudio(data.data); break;
                case "avatar_telemetry": handleAvatarTelemetry(data.volume); break;
                case "emotion_changed":  handleAvatarEmotion(data.emotion); break;
            }
        } catch (e) {
            console.error("Failed to parse WebSocket message:", e);
        }
    };

    ws.onclose = () => {
        console.log("WebSocket disconnected");
        statusTextElement.innerText = "Disconnected";
        statusTextElement.className = "status-offline";
        showToast("Connection lost — reconnecting…");
        scheduleReconnect();
    };
}

function scheduleReconnect() {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = setTimeout(connectWebSocket, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 1.6, 15000);
}

let sttEchoTracker = null;

function appendUserMessage(text) {
    const el = createMessageElement(text, 'user', Date.now().toString(), { isNew: true });
    chatContainer.appendChild(el);
    scrollToBottom(true);
    hideTypingIndicator();
    playPop(true);
}

function onBroadcastUserMessage(text) {
    const t = sttEchoTracker;
    if (t && t.text === text && Date.now() - t.ts < 10000) {
        if (!t.rendered) {
            t.rendered = true;
            appendUserMessage(text);
        }
        return;
    }
    appendUserMessage(text);
}

function handleIncomingChunk(text) {
    hideTypingIndicator();
    if (!currentMessageDiv) {
        currentMessageDiv = createMessageElement("", 'waifu', currentMessageId);
        chatContainer.appendChild(currentMessageDiv);
    }
    currentMessageDiv.dataset.rawText += text;
    const contentDiv = currentMessageDiv.querySelector('.msg-content');
    if (contentDiv) {
        contentDiv.innerHTML = marked.parse(currentMessageDiv.dataset.rawText);
    } else {
        console.error("[Stream] .msg-content not found — message bubble markup mismatch");
    }
    scrollToBottom();
}

// ── Message rendering ─────────────────────────────────────────────
const USER_AVATAR_PLACEHOLDER = "data:image/svg+xml;utf8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="60" height="60"><rect width="60" height="60" rx="30" fill="#1F2937"/><circle cx="30" cy="24" r="10" fill="#4B5563"/><path d="M12 52c2-10 9-14 18-14s16 4 18 14" fill="#4B5563"/></svg>`
);

function createMessageElement(text, side, id, meta = {}) {
    const div = document.createElement('div');
    div.className = `message ${side}`;
    if (id) div.id = `msg-${id}`;
    div.dataset.rawText = text || "";

    const avatar = document.createElement('img');
    avatar.className = 'msg-avatar';
    avatar.loading = 'lazy';
    if (side === 'waifu') {
        avatar.src = withToken('/api/avatar/' + encodeURIComponent(currentCharacter));
        avatar.alt = currentCharacter;
    } else {
        avatar.src = USER_AVATAR_PLACEHOLDER;
        avatar.alt = userName;
    }

    const body = document.createElement('div');
    body.className = 'msg-body';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'msg-bubble msg-content';
    contentDiv.innerHTML = marked.parse(text || "");
    body.appendChild(contentDiv);

    const metaDiv = document.createElement('div');
    metaDiv.className = 'msg-meta';
    const author = meta.author || (side === 'user' ? userName : currentCharacter);
    const time = formatTime(meta.created_at) || (meta.isNew ? formatTime(new Date().toISOString()) : "");
    metaDiv.innerHTML = `<span class="msg-author">${escapeHtml(author)}</span>` +
                        (time ? `<span class="msg-time">${time}</span>` : "");
    body.appendChild(metaDiv);

    if (id) {
        const controls = document.createElement('div');
        controls.className = 'msg-controls';

        const editBtn = document.createElement('button');
        editBtn.className = 'control-btn';
        editBtn.title = "Edit";
        editBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
        editBtn.onclick = () => enableEditMode(div, id);
        controls.appendChild(editBtn);

        if (side === 'waifu') {
            const regenBtn = document.createElement('button');
            regenBtn.className = 'control-btn';
            regenBtn.title = "Regenerate";
            regenBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>`;
            regenBtn.onclick = () => {
                showToast("Regenerating…");
                pendingRegenReload = true;
                regenerateMessage(id);
            };
            controls.appendChild(regenBtn);
        }

        const delBtn = document.createElement('button');
        delBtn.className = 'control-btn';
        delBtn.title = "Delete";
        delBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
        delBtn.onclick = () => deleteMessage(id);
        controls.appendChild(delBtn);

        body.appendChild(controls);

        if (side === 'waifu') {
            const vc = meta.variant_count || 0;
            const vi = meta.variant_index || 0;
            const variantBar = document.createElement('div');
            variantBar.className = 'msg-variants';
            variantBar.dataset.count = vc;
            variantBar.dataset.index = vi;
            if (vc > 1) variantBar.classList.add('has-variants');

            const prevBtn = document.createElement('button');
            prevBtn.className = 'variant-btn';
            prevBtn.title = "Previous response";
            prevBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>`;
            prevBtn.onclick = (e) => { e.stopPropagation(); switchVariant(id, -1); };

            const counter = document.createElement('span');
            counter.className = 'variant-counter';
            counter.textContent = `${vi + 1}/${vc}`;
            counter.title = `Response ${vi + 1} of ${vc}`;

            const nextBtn = document.createElement('button');
            nextBtn.className = 'variant-btn';
            nextBtn.title = "Next response";
            nextBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>`;
            nextBtn.onclick = (e) => { e.stopPropagation(); switchVariant(id, 1); };

            variantBar.appendChild(prevBtn);
            variantBar.appendChild(counter);
            variantBar.appendChild(nextBtn);
            body.appendChild(variantBar);
        }

        div.addEventListener('click', (e) => {
            if (e.target.closest('.msg-controls') || e.target.closest('.edit-input') || e.target.closest('.edit-actions')) return;
            const ctr = div.querySelector('.msg-controls');
            if (ctr) {
                document.querySelectorAll('.msg-controls.mobile-active').forEach(p => {
                    if (p !== ctr) p.classList.remove('mobile-active');
                });
                ctr.classList.toggle('mobile-active');
            }
        });
    }

    div.appendChild(avatar);
    div.appendChild(body);
    return div;
}

function enableEditMode(div, id) {
    if (div.querySelector('.edit-input')) return;
    const contentDiv = div.querySelector('.msg-content');
    const rawText    = div.dataset.rawText;

    div.classList.add('editing');

    const input      = document.createElement('textarea');
    input.className  = 'edit-input';
    input.value      = rawText;

    const actions    = document.createElement('div');
    actions.className = 'edit-actions';

    const cancelEdit = () => {
        div.classList.remove('editing');
        input.remove(); actions.remove();
        contentDiv.style.display = 'block';
    };

    const saveBtn    = document.createElement('button');
    saveBtn.innerText = 'Save';
    saveBtn.onclick  = async () => {
        const newText = input.value;
        const resp = await authFetch(`/api/messages/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: currentCharacter, text: newText })
        });
        if (resp.ok) {
            cancelEdit();
            div.dataset.rawText = newText;
            contentDiv.innerHTML = marked.parse(newText);
        } else {
            showToast("Failed to save changes");
        }
    };

    const cancelBtn  = document.createElement('button');
    cancelBtn.innerText = 'Cancel';
    cancelBtn.onclick = cancelEdit;

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);

    contentDiv.style.display = 'none';
    const body = div.querySelector('.msg-body');
    body.insertBefore(input,   div.querySelector('.msg-controls'));
    body.insertBefore(actions, div.querySelector('.msg-controls'));
    input.focus();
}

async function deleteMessage(id) {
    if (!confirm("Delete this message?")) return;
    await authFetch(`/api/messages/${id}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character: currentCharacter })
    });
}

async function regenerateMessage(id) {
    historyOffset = 0;
    await authFetch(`/api/messages/${id}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character: currentCharacter })
    });
}

async function switchVariant(id, direction) {
    try {
        const resp = await authFetch(`/api/messages/${id}/variant`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character: currentCharacter, direction })
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.message || "No variants");
            return;
        }
        const data = await resp.json();
        const el = document.getElementById(`msg-${id}`);
        if (el && data.text !== undefined) {
            el.dataset.rawText = data.text;
            const c = el.querySelector('.msg-content');
            if (c) c.innerHTML = marked.parse(data.text);
            const bar = el.querySelector('.msg-variants');
            if (bar && data.total) {
                bar.dataset.count = data.total;
                bar.dataset.index = (data.current || 1) - 1;
                const counter = bar.querySelector('.variant-counter');
                if (counter) {
                    counter.textContent = `${data.current}/${data.total}`;
                    counter.title = `Response ${data.current} of ${data.total}`;
                }
            }
        }
    } catch (e) {
        console.error("switchVariant failed", e);
        showToast("Failed to switch variant");
    }
}

// ── Typing / send ─────────────────────────────────────────────────
function showTypingIndicator() {
    typingIndicator.classList.remove('hidden');
    typingIndicator.classList.add('visible');
    chatContainer.appendChild(typingIndicator);
    scrollToBottom();
}

function hideTypingIndicator() {
    typingIndicator.classList.remove('visible');
    typingIndicator.classList.add('hidden');
    if (typingIndicator.parentElement !== document.body) {
        document.body.appendChild(typingIndicator);
    }
}

function sendMessage() {
    const text = msgInput.value.trim();
    if (!text) return;

    if (!currentCharacter) { showToast("Select a character first"); return; }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showToast("Connection lost — reconnecting…");
        msgInput.value = text;
        scheduleReconnect();
        return;
    }

    msgInput.value = "";
    msgInput.style.height = 'auto';
    sendBtn.classList.remove('active');

    ws.send(JSON.stringify({ type: "user_input", character: currentCharacter, text }));

    appendUserMessage(text);
    showTypingIndicator();
}

function scrollToBottom(force = false) {
    if (force) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
        scrollBottomBtn.classList.add('hidden');
        return;
    }
    const threshold = 150;
    const isNearBottom = (chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight) < threshold;
    if (isNearBottom) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

scrollBottomBtn.onclick = () => scrollToBottom(true);

msgInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});

sendBtn.onclick           = sendMessage;
msgInput.onkeypress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
};
msgInput.oninput          = (e) => { sendBtn.classList.toggle('active', e.target.value.trim().length > 0); };
if (stopBtn) stopBtn.onclick = async () => {
    await authFetch('/api/generation/stop', { method: 'POST' });
    hideTypingIndicator();
};

// ── TTS audio from desktop ────────────────────────────────────────
function handleIncomingAudio(b64Audio) {
    if (!settings.tts) return;
    audioQueue.push(b64Audio);
    if (!isPlayingAudio) playNextAudio();
}

function playNextAudio() {
    if (audioQueue.length === 0) { isPlayingAudio = false; return; }
    isPlayingAudio = true;
    const audio = new Audio("data:audio/wav;base64," + audioQueue.shift());
    audio.onended  = () => playNextAudio();
    audio.onerror  = () => playNextAudio();
    audio.play().catch(() => playNextAudio());
}

// ── Voice input ───────────────────────────────────────────────────
async function toggleRecording() {
    if (!isRecording) {
        try {
            const stream    = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder   = new MediaRecorder(stream);
            audioChunks     = [];

            mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.onstop = async () => {
                micBtn.classList.remove('recording');
                isRecording = false;
                if (audioChunks.length === 0) return;

                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const formData  = new FormData();
                formData.append('audio',     audioBlob, 'recording.webm');
                formData.append('character', currentCharacter);
                showTypingIndicator();

                try {
                    const resp   = await authFetch('/api/voice/stt', { method: 'POST', body: formData });
                    const result = await resp.json();
                    if (result.status === 'ok' && result.text) {
                        sttEchoTracker = { text: result.text, ts: Date.now(), rendered: false };
                        setTimeout(() => {
                            hideTypingIndicator();
                            if (sttEchoTracker && !sttEchoTracker.rendered) {
                                sttEchoTracker.rendered = true;
                                appendUserMessage(sttEchoTracker.text);
                            }
                        }, 2000);
                    } else {
                        hideTypingIndicator();
                    }
                } catch (e) {
                    hideTypingIndicator();
                    console.error("STT Error:", e);
                }
                stream.getTracks().forEach(t => t.stop());
            };

            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add('recording');
        } catch (e) {
            console.error("Microphone access denied:", e);
            showToast("Failed to access the microphone");
        }
    } else {
        if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
    }
}

if (micBtn) micBtn.onclick = toggleRecording;

if (menuBtn) menuBtn.onclick = (e) => {
    e.stopPropagation();
    loadCharacters();
    openDrawer('characters-drawer');
};

document.getElementById('chats-btn').onclick = (e) => {
    e.stopPropagation();
    loadChats();
    openDrawer('chats-drawer');
};

document.getElementById('settings-btn').onclick = (e) => {
    e.stopPropagation();
    openDrawer('settings-drawer');
};

document.getElementById('topbar-identity').onclick = () => {
    loadChats();
    openDrawer('chats-drawer');
};

document.querySelectorAll('.accent-swatch').forEach(s => {
    s.addEventListener('click', () => {
        settings.accent = s.dataset.accent;
        saveSettings();
        applySettings();
    });
});
document.getElementById('accent-custom')?.addEventListener('input', (e) => {
    settings.accent = 'custom';
    settings.accentCustom = e.target.value;
    saveSettings();
    applySettings();
});
document.getElementById('font-scale').addEventListener('input', (e) => {
    settings.fontScale = parseInt(e.target.value, 10);
    saveSettings();
    applySettings();
});
document.getElementById('dim-range')?.addEventListener('input', (e) => {
    settings.dim = parseInt(e.target.value, 10);
    saveSettings();
    applySettings();
});
document.getElementById('chatwidth-range')?.addEventListener('input', (e) => {
    settings.chatWidth = parseInt(e.target.value, 10);
    saveSettings();
    applySettings();
});
document.getElementById('stageheight-range')?.addEventListener('input', (e) => {
    settings.stageHeight = parseInt(e.target.value, 10);
    saveSettings();
    applySettings();
    if (pixiApp) { pixiApp.resize(); fitLive2D(); }
});
document.getElementById('sound-toggle').addEventListener('change', (e) => {
    settings.sound = e.target.checked; saveSettings();
    if (settings.sound) playPop(false);
});
document.getElementById('tts-toggle').addEventListener('change', (e) => {
    settings.tts = e.target.checked; saveSettings();
    if (!settings.tts) { audioQueue = []; }
});
document.getElementById('avatars-toggle').addEventListener('change', (e) => {
    settings.avatars = e.target.checked; saveSettings(); applySettings();
});
document.getElementById('timestamps-toggle').addEventListener('change', (e) => {
    settings.timestamps = e.target.checked; saveSettings(); applySettings();
});
document.getElementById('motion-toggle')?.addEventListener('change', (e) => {
    settings.reduceMotion = e.target.checked; saveSettings(); applySettings();
});
document.getElementById('oled-toggle')?.addEventListener('change', (e) => {
    settings.oled = e.target.checked; saveSettings(); applySettings();
});
document.getElementById('collapse-stage-toggle')?.addEventListener('change', (e) => {
    settings.stageCollapsed = e.target.checked; saveSettings(); applySettings();
    if (!e.target.checked && pixiApp) setTimeout(() => { pixiApp.resize(); fitLive2D(); }, 60);
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeDrawers(); stagePanel?.classList.add('hidden'); }
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        openDrawer('chats-drawer'); loadChats();
    }
});

function checkStylesheetHealth() {
    setTimeout(() => {
        let ok = true;
        try {
            ok = getComputedStyle(document.body).display === 'flex' &&
                 getComputedStyle(document.querySelector('.topbar')).display === 'flex';
        } catch (e) { ok = false; }

        if (!ok) {
            console.error('[SoW] Stylesheet did not apply — reloading with cache bust');
            if (!sessionStorage.getItem('sow_css_reload_done')) {
                sessionStorage.setItem('sow_css_reload_done', '1');
                const sep = location.search ? '&' : '?';
                location.replace(location.href.split('#')[0] + sep + '_css=' + Date.now());
            } else {
                showToast("Styles failed to load — обновите страницу или проверьте соединение", 6000);
            }
        } else {
            sessionStorage.removeItem('sow_css_reload_done');
        }
    }, 900);
}

checkStylesheetHealth();
init();
