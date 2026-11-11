/**
 * WebAuthn / Passkey Client Helpers
 * Dual-engine support: SimpleWebAuthnBrowser + Pure Native WebAuthn fallback.
 * 100% resilient across all browsers (iOS Safari, Android Chrome, macOS, Windows).
 */

function base64UrlToBuffer(base64url) {
    if (!base64url || typeof base64url !== 'string') {
        throw new Error('无效的凭据数据编码');
    }
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    const pad = (4 - (base64.length % 4)) % 4;
    const binary = atob(base64.padEnd(base64.length + pad, '='));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}

function bufferToBase64Url(buffer) {
    if (!buffer) return '';
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function safeStartRegistration(rawOptions) {
    // Unpack options if wrapped
    const options = rawOptions.optionsJSON || rawOptions.options || rawOptions;

    // 1. Try SimpleWebAuthnBrowser if available
    if (window.SimpleWebAuthnBrowser && typeof window.SimpleWebAuthnBrowser.startRegistration === 'function') {
        try {
            return await window.SimpleWebAuthnBrowser.startRegistration(options);
        } catch (e) {
            if (e.name === 'NotAllowedError') throw e;
            console.warn('SimpleWebAuthn helper error, falling back to Native WebAuthn API:', e);
        }
    }

    // 2. Native WebAuthn API Fallback
    const excludeCredentials = (options.excludeCredentials || []).map(c => ({
        ...c,
        id: typeof c.id === 'string' ? base64UrlToBuffer(c.id) : c.id,
    }));

    const publicKey = {
        ...options,
        challenge: base64UrlToBuffer(options.challenge),
        user: {
            ...options.user,
            id: base64UrlToBuffer(options.user.id),
        },
        excludeCredentials: excludeCredentials,
    };

    const cred = await navigator.credentials.create({ publicKey });
    if (!cred) throw new Error('Passkey 凭据创建失败或被取消');

    const res = cred.response;
    return {
        id: cred.id,
        rawId: bufferToBase64Url(cred.rawId),
        response: {
            attestationObject: bufferToBase64Url(res.attestationObject),
            clientDataJSON: bufferToBase64Url(res.clientDataJSON),
            transports: typeof res.getTransports === 'function' ? res.getTransports() : [],
        },
        type: cred.type,
    };
}

async function safeStartAuthentication(rawOptions) {
    const options = rawOptions.optionsJSON || rawOptions.options || rawOptions;

    // 1. Try SimpleWebAuthnBrowser if available
    if (window.SimpleWebAuthnBrowser && typeof window.SimpleWebAuthnBrowser.startAuthentication === 'function') {
        try {
            return await window.SimpleWebAuthnBrowser.startAuthentication(options);
        } catch (e) {
            if (e.name === 'NotAllowedError') throw e;
            console.warn('SimpleWebAuthn helper error, falling back to Native WebAuthn API:', e);
        }
    }

    // 2. Native WebAuthn API Fallback
    const allowCredentials = (options.allowCredentials || []).map(c => ({
        ...c,
        id: typeof c.id === 'string' ? base64UrlToBuffer(c.id) : c.id,
    }));

    const publicKey = {
        ...options,
        challenge: base64UrlToBuffer(options.challenge),
        allowCredentials: allowCredentials,
    };

    const cred = await navigator.credentials.get({ publicKey });
    if (!cred) throw new Error('Passkey 认证失败或被取消');

    const res = cred.response;
    return {
        id: cred.id,
        rawId: bufferToBase64Url(cred.rawId),
        response: {
            authenticatorData: bufferToBase64Url(res.authenticatorData),
            clientDataJSON: bufferToBase64Url(res.clientDataJSON),
            signature: bufferToBase64Url(res.signature),
            userHandle: res.userHandle ? bufferToBase64Url(res.userHandle) : null,
        },
        type: cred.type,
    };
}

const WebAuthnClient = {
    /**
     * Check if the browser supports WebAuthn / Passkeys
     */
    isSupported() {
        return (
            window.PublicKeyCredential !== undefined &&
            typeof window.PublicKeyCredential === 'function' &&
            navigator.credentials !== undefined &&
            typeof navigator.credentials.create === 'function'
        );
    },

    /**
     * Check if context is secure (HTTPS or localhost is required by browser security spec)
     */
    isSecure() {
        return window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    },

    /**
     * Register a new user with Passkey or initialize first admin
     */
    async registerUser(username, displayName, deviceName) {
        if (!this.isSupported()) {
            throw new Error('当前浏览器不支持 Passkey / WebAuthn，请使用现代浏览器（如 iOS Safari、Chrome、Edge）');
        }

        // 1. Get registration options from server
        const optRes = await fetch('/api/auth/register-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: username.trim(),
                display_name: displayName ? displayName.trim() : username.trim(),
            }),
        });

        if (!optRes.ok) {
            const err = await optRes.json();
            throw new Error(err.detail || '获取注册挑战失败');
        }

        const optData = await optRes.json();
        const challengeId = optData.challenge_id;
        const optionsJSON = optData.options;

        // 2. Trigger browser passkey registration prompt (Biometric / Security Key)
        let credential;
        try {
            credential = await safeStartRegistration(optionsJSON);
        } catch (err) {
            console.error('Passkey registration error:', err);
            if (err.name === 'NotAllowedError') {
                throw new Error('您取消了 Passkey 验证或验证超时');
            }
            throw new Error(err.message || 'Passkey 创建失败');
        }

        // 3. Verify credential with server
        const verifyRes = await fetch('/api/auth/register-verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                challenge_id: challengeId,
                credential: credential,
                device_name: deviceName || '当前设备',
            }),
        });

        if (!verifyRes.ok) {
            const err = await verifyRes.json();
            throw new Error(err.detail || 'Passkey 验证失败');
        }

        return await verifyRes.json();
    },

    /**
     * Register an additional device / backup Passkey for the current logged-in user
     */
    async addPasskey(deviceName) {
        if (!this.isSupported()) {
            throw new Error('当前浏览器不支持 Passkey');
        }

        const optRes = await fetch('/api/user/passkeys/add-options');
        if (!optRes.ok) {
            const err = await optRes.json();
            throw new Error(err.detail || '获取添加凭据挑战失败');
        }

        const optData = await optRes.json();
        const challengeId = optData.challenge_id;
        const optionsJSON = optData.options;

        let credential;
        try {
            credential = await safeStartRegistration(optionsJSON);
        } catch (err) {
            if (err.name === 'NotAllowedError') {
                throw new Error('您取消了验证或超时');
            }
            throw new Error(err.message || '添加凭据失败');
        }

        const verifyRes = await fetch('/api/auth/register-verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                challenge_id: challengeId,
                credential: credential,
                device_name: deviceName || '新绑定设备',
            }),
        });

        if (!verifyRes.ok) {
            const err = await verifyRes.json();
            throw new Error(err.detail || '验证失败');
        }

        return await verifyRes.json();
    },

    /**
     * Log in using Passkey
     */
    async login(username = null) {
        if (!this.isSupported()) {
            throw new Error('当前浏览器不支持 Passkey / WebAuthn');
        }

        // 1. Get authentication options from server
        const optRes = await fetch('/api/auth/login-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username ? username.trim() : null }),
        });

        if (!optRes.ok) {
            const err = await optRes.json();
            throw new Error(err.detail || '获取登录选项失败');
        }

        const optData = await optRes.json();
        const challengeId = optData.challenge_id;
        const optionsJSON = optData.options;

        // 2. Trigger browser passkey login prompt
        let credential;
        try {
            credential = await safeStartAuthentication(optionsJSON);
        } catch (err) {
            console.error('Passkey login error:', err);
            if (err.name === 'NotAllowedError') {
                throw new Error('您取消了登录或验证未通过');
            }
            throw new Error(err.message || 'Passkey 登录失败');
        }

        // 3. Verify assertion with server
        const verifyRes = await fetch('/api/auth/login-verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                challenge_id: challengeId,
                credential: credential,
            }),
        });

        if (!verifyRes.ok) {
            const err = await verifyRes.json();
            throw new Error(err.detail || 'Passkey 校验失败');
        }

        return await verifyRes.json();
    },
};

window.WebAuthnClient = WebAuthnClient;
