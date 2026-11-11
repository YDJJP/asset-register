/**
 * WebAuthn / Passkey Client Helpers
 * Uses SimpleWebAuthnBrowser for standards-compliant credential creation & assertion.
 */

const WebAuthnClient = {
    /**
     * Check if the browser supports WebAuthn / Passkeys
     */
    isSupported() {
        return (
            window.PublicKeyCredential !== undefined &&
            typeof window.PublicKeyCredential === 'function' &&
            window.SimpleWebAuthnBrowser !== undefined
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
            throw new Error('当前浏览器不支持 Passkey / WebAuthn，请使用现代浏览器（如 Chrome、Safari、Edge）');
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
            const opts = optionsJSON.optionsJSON || optionsJSON;
            credential = await window.SimpleWebAuthnBrowser.startRegistration(opts);
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
            const opts = optionsJSON.optionsJSON || optionsJSON;
            credential = await window.SimpleWebAuthnBrowser.startRegistration(opts);
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
            const opts = optionsJSON.optionsJSON || optionsJSON;
            credential = await window.SimpleWebAuthnBrowser.startAuthentication(opts);
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

