const { createApp, ref, computed, onMounted, nextTick } = Vue;

const app = createApp({
    setup() {
        // --- Auth State ---
        const authStatus = ref({
            has_users: true,
            is_authenticated: false,
            user: null,
            rp_id: '',
            origin: '',
        });
        const isAuthChecking = ref(true);
        const isSecureContext = ref(window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

        // Setup / Login Forms
        const setupForm = ref({ username: 'admin', displayName: '系统管理员', deviceName: '首台管理设备' });
        const loginForm = ref({ username: '' });
        const authLoading = ref(false);
        const authError = ref('');

        // --- User / Passkey Management ---
        const showUserModal = ref(false);
        const userPasskeys = ref([]);
        const newDeviceName = ref('');
        const isAddingPasskey = ref(false);

        // --- Asset List State ---
        const assets = ref([]);
        const totalAssets = ref(0);
        const currentPage = ref(1);
        const pageSize = ref(40);
        const totalPages = ref(1);
        const isLoadingAssets = ref(false);
        const viewMode = ref('grid'); // 'grid' or 'table'

        // Filters
        const searchQuery = ref('');
        const selectedLocation = ref('');
        const selectedCategory = ref('');
        const selectedStatus = ref('');

        // Metadata & Stats
        const locationsList = ref([]);
        const stats = ref({
            total_assets: 0,
            total_images: 0,
            total_locations: 0,
            by_status: [],
            by_category: [],
        });

        // Modals State
        const showAssetModal = ref(false);
        const isEditing = ref(false);
        const assetForm = ref({
            id: '',
            name: '',
            location: '',
            category: '通用',
            status: '在用',
            description: '',
        });
        const pendingImages = ref([]); // File objects for new asset creation
        const isSavingAsset = ref(false);
        const isRecognizingId = ref(false);
        const idCandidates = ref([]);

        // Asset Detail View
        const showDetailModal = ref(false);
        const activeAsset = ref(null);
        const activeImageIndex = ref(0);
        const isUploadingMoreImages = ref(false);

        // Fullscreen Lightbox
        const showLightbox = ref(false);
        const lightboxImageUrl = ref('');

        // QR Code / Label Print Modal
        const showLabelModal = ref(false);
        const labelAsset = ref(null);

        // Scanner Modal
        const showScannerModal = ref(false);
        let html5QrCodeScanner = null;

        // Toast Notifications
        const toast = ref({ show: false, message: '', type: 'success' });
        const showToast = (message, type = 'success') => {
            toast.value = { show: true, message, type };
            setTimeout(() => {
                toast.value.show = false;
            }, 3500);
        };

        const refreshIcons = () => {
            nextTick(() => {
                if (!window.lucide || !window.lucide.icons) return;
                document.querySelectorAll('[data-lucide]').forEach((el) => {
                    const iconName = el.getAttribute('data-lucide');
                    if (!iconName) return;
                    if (el.getAttribute('data-rendered') === iconName && el.querySelector('svg')) return;

                    const pascalName = iconName
                        .split('-')
                        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
                        .join('');

                    const iconNode = window.lucide.icons[pascalName] || window.lucide.icons[iconName];
                    if (iconNode) {
                        const svg = window.lucide.createElement(iconNode, {
                            class: el.getAttribute('class') || '',
                        });
                        // Safe rendering: NEVER detach el from parent (prevents Vue Virtual DOM insertBefore null crash)
                        el.replaceChildren(svg);
                        el.setAttribute('data-rendered', iconName);
                    }
                });
            });
        };

        // -------------------------------------------------------------
        // Auth Lifecycle
        // -------------------------------------------------------------
        const checkAuthStatus = async () => {
            isAuthChecking.value = true;
            try {
                const res = await fetch('/api/auth/status');
                if (res.ok) {
                    authStatus.value = await res.json();
                    if (authStatus.value.is_authenticated) {
                        await loadAssets();
                        await loadStats();
                        await loadLocations();
                    }
                }
            } catch (err) {
                console.error('Failed to check auth status:', err);
            } finally {
                isAuthChecking.value = false;
                refreshIcons();
            }
        };

        // First-time Passkey setup
        const handleInitialSetup = async () => {
            authLoading.value = true;
            authError.value = '';
            try {
                const result = await WebAuthnClient.registerUser(
                    setupForm.value.username,
                    setupForm.value.displayName,
                    setupForm.value.deviceName
                );
                showToast('管理员账号及 Passkey 初始化成功！');
                await checkAuthStatus();
            } catch (err) {
                authError.value = err.message || 'Passkey 注册失败';
            } finally {
                authLoading.value = false;
            }
        };

        // Passkey Login
        const handlePasskeyLogin = async () => {
            authLoading.value = true;
            authError.value = '';
            try {
                const result = await WebAuthnClient.login(loginForm.value.username);
                showToast('Passkey 登录成功！');
                await checkAuthStatus();
            } catch (err) {
                authError.value = err.message || 'Passkey 登录未成功';
            } finally {
                authLoading.value = false;
            }
        };

        // Logout
        const handleLogout = async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
                authStatus.value.is_authenticated = false;
                authStatus.value.user = null;
                showToast('已安全退出登录');
                await checkAuthStatus();
            } catch (err) {
                console.error('Logout error:', err);
            }
        };

        // Open User / Security Settings
        const openUserModal = async () => {
            showUserModal.value = true;
            await loadUserPasskeys();
            refreshIcons();
        };

        const loadUserPasskeys = async () => {
            try {
                const res = await fetch('/api/user/me');
                if (res.ok) {
                    const data = await res.json();
                    userPasskeys.value = data.passkeys;
                }
            } catch (err) {
                console.error(err);
            }
        };

        const handleAddPasskey = async () => {
            isAddingPasskey.value = true;
            try {
                const devName = newDeviceName.value.trim() || '备用凭据设备';
                await WebAuthnClient.addPasskey(devName);
                newDeviceName.value = '';
                showToast('新 Passkey 设备绑定成功！');
                await loadUserPasskeys();
            } catch (err) {
                showToast(err.message || '添加失败', 'error');
            } finally {
                isAddingPasskey.value = false;
            }
        };

        const handleDeletePasskey = async (passkeyId) => {
            if (!confirm('确定要移除此 Passkey 设备凭据吗？')) return;
            try {
                const res = await fetch(`/api/user/passkeys/${passkeyId}`, { method: 'DELETE' });
                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.detail || '删除失败');
                }
                showToast('Passkey 凭据已移除');
                await loadUserPasskeys();
            } catch (err) {
                showToast(err.message, 'error');
            }
        };

        // -------------------------------------------------------------
        // Assets Management
        // -------------------------------------------------------------
        const loadAssets = async (page = 1) => {
            isLoadingAssets.value = true;
            currentPage.value = page;
            try {
                const params = new URLSearchParams({
                    page: page.toString(),
                    limit: pageSize.value.toString(),
                });
                if (searchQuery.value.trim()) params.append('q', searchQuery.value.trim());
                if (selectedLocation.value) params.append('location', selectedLocation.value);
                if (selectedCategory.value) params.append('category', selectedCategory.value);
                if (selectedStatus.value) params.append('status', selectedStatus.value);

                const res = await fetch(`/api/assets?${params.toString()}`);
                if (res.ok) {
                    const data = await res.json();
                    assets.value = data.items;
                    totalAssets.value = data.total;
                    totalPages.value = data.pages;
                }
            } catch (err) {
                console.error('Failed to load assets:', err);
            } finally {
                isLoadingAssets.value = false;
                refreshIcons();
            }
        };

        const loadStats = async () => {
            try {
                const res = await fetch('/api/assets/meta/stats');
                if (res.ok) stats.value = await res.json();
            } catch (err) {
                console.error(err);
            }
        };

        const loadLocations = async () => {
            try {
                const res = await fetch('/api/assets/meta/locations');
                if (res.ok) locationsList.value = await res.json();
            } catch (err) {
                console.error(err);
            }
        };

        // Auto-generate Asset ID
        const generateAssetId = () => {
            const dateStr = new Date().toISOString().slice(2, 10).replace(/-/g, '');
            const randSuffix = Math.floor(1000 + Math.random() * 9000);
            assetForm.value.id = `AST-${dateStr}-${randSuffix}`;
        };

        // Open Add Asset Modal
        const openAddModal = () => {
            isEditing.value = false;
            assetForm.value = {
                id: '',
                name: '',
                location: selectedLocation.value || '',
                category: '通用',
                status: '在用',
                description: '',
            };
            pendingImages.value = [];
            generateAssetId();
            showAssetModal.value = true;
            refreshIcons();
        };

        // Open Edit Asset Modal
        const openEditModal = (asset) => {
            isEditing.value = true;
            assetForm.value = {
                id: asset.id,
                name: asset.name,
                location: asset.location,
                category: asset.category || '通用',
                status: asset.status || '在用',
                description: asset.description || '',
            };
            pendingImages.value = [];
            showAssetModal.value = true;
            refreshIcons();
        };

        // File / Camera Selection for New Asset
        const handleFilesSelected = (event) => {
            const files = Array.from(event.target.files || []);
            addFilesToPending(files);
            event.target.value = '';
        };

        const handleDrop = (event) => {
            const files = Array.from(event.dataTransfer.files || []).filter(f => f.type.startsWith('image/'));
            addFilesToPending(files);
        };

        const handlePaste = (event) => {
            const items = (event.clipboardData || event.originalEvent.clipboardData).items;
            const pastedFiles = [];
            for (let item of items) {
                if (item.type.indexOf('image') !== -1) {
                    const blob = item.getAsFile();
                    if (blob) pastedFiles.push(blob);
                }
            }
            if (pastedFiles.length > 0) {
                addFilesToPending(pastedFiles);
                showToast(`已从剪贴板粘贴 ${pastedFiles.length} 张图片`);
            }
        };

        const recognizeIdFromFile = async (file) => {
            if (!file) return;
            isRecognizingId.value = true;
            idCandidates.value = [];
            try {
                const formData = new FormData();
                formData.append('file', file);
                const res = await fetch('/api/assets/recognize-id', {
                    method: 'POST',
                    body: formData,
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.best_id) {
                        assetForm.value.id = data.best_id;
                        idCandidates.value = data.candidates || [];
                        showToast(`✨ 已智能识别编号: ${data.best_id}`);
                    } else {
                        showToast('未在图片中检测到明显的资产编号或条码', 'info');
                    }
                }
            } catch (err) {
                console.error('ID recognition error:', err);
            } finally {
                isRecognizingId.value = false;
                refreshIcons();
            }
        };

        const addFilesToPending = (files) => {
            for (let file of files) {
                const previewUrl = URL.createObjectURL(file);
                pendingImages.value.push({ file, previewUrl, name: file.name, size: file.size });
            }
            refreshIcons();

            // Automatically trigger OCR / Barcode recognition on first image
            if (files.length > 0 && (!assetForm.value.id || assetForm.value.id.startsWith('AST-'))) {
                recognizeIdFromFile(files[0]);
            }
        };

        const triggerManualRecognize = (file) => {
            if (file) {
                recognizeIdFromFile(file);
            } else if (pendingImages.value.length > 0) {
                recognizeIdFromFile(pendingImages.value[0].file);
            } else {
                showToast('请先选择或拍摄一张照片', 'error');
            }
        };

        const removePendingImage = (index) => {
            const item = pendingImages.value.splice(index, 1)[0];
            if (item && item.previewUrl) {
                URL.revokeObjectURL(item.previewUrl);
            }
        };

        // Save Asset (Create or Update)
        const saveAsset = async () => {
            if (!assetForm.value.id.trim()) {
                showToast('请输入或生成资产编号(ID)', 'error');
                return;
            }
            if (!assetForm.value.name.trim()) {
                showToast('请输入资产名称', 'error');
                return;
            }
            if (!assetForm.value.location.trim()) {
                showToast('请指定资产存放位置(Location)', 'error');
                return;
            }

            isSavingAsset.value = true;
            try {
                if (!isEditing.value) {
                    // Create
                    const createRes = await fetch('/api/assets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(assetForm.value),
                    });
                    if (!createRes.ok) {
                        const err = await createRes.json();
                        throw new Error(err.detail || '创建资产失败');
                    }

                    // If images were selected, upload them now
                    if (pendingImages.value.length > 0) {
                        const formData = new FormData();
                        for (let p of pendingImages.value) {
                            formData.append('files', p.file);
                        }
                        await fetch(`/api/assets/${encodeURIComponent(assetForm.value.id)}/images`, {
                            method: 'POST',
                            body: formData,
                        });
                    }
                    showToast('资产登记成功！');
                } else {
                    // Update
                    const updateRes = await fetch(`/api/assets/${encodeURIComponent(assetForm.value.id)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name: assetForm.value.name,
                            location: assetForm.value.location,
                            category: assetForm.value.category,
                            status: assetForm.value.status,
                            description: assetForm.value.description,
                        }),
                    });
                    if (!updateRes.ok) {
                        const err = await updateRes.json();
                        throw new Error(err.detail || '更新失败');
                    }
                    showToast('资产信息已更新');
                }

                showAssetModal.value = false;
                await loadAssets(currentPage.value);
                await loadStats();
                await loadLocations();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                isSavingAsset.value = false;
            }
        };

        // -------------------------------------------------------------
        // Detail View & Image Operations
        // -------------------------------------------------------------
        const openDetail = async (assetId) => {
            try {
                const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}`);
                if (res.ok) {
                    activeAsset.value = await res.json();
                    activeImageIndex.value = 0;
                    showDetailModal.value = true;
                    refreshIcons();
                } else {
                    showToast('未找到该资产详情', 'error');
                }
            } catch (err) {
                console.error(err);
            }
        };

        const handleUploadMoreImages = async (event) => {
            const files = Array.from(event.target.files || []);
            if (files.length === 0 || !activeAsset.value) return;

            isUploadingMoreImages.value = true;
            try {
                const formData = new FormData();
                for (let f of files) formData.append('files', f);

                const res = await fetch(`/api/assets/${encodeURIComponent(activeAsset.value.id)}/images`, {
                    method: 'POST',
                    body: formData,
                });
                if (!res.ok) throw new Error('上传图片失败');

                showToast(`已追加上传 ${files.length} 张图片`);
                // Reload active asset detail
                await openDetail(activeAsset.value.id);
                await loadAssets(currentPage.value);
                await loadStats();
            } catch (err) {
                showToast(err.message, 'error');
            } finally {
                isUploadingMoreImages.value = false;
                event.target.value = '';
            }
        };

        const handleSetPrimaryImage = async (imageId) => {
            if (!activeAsset.value) return;
            try {
                const res = await fetch(`/api/assets/${encodeURIComponent(activeAsset.value.id)}/images/${imageId}/primary`, {
                    method: 'POST',
                });
                if (res.ok) {
                    showToast('已设为主图');
                    await openDetail(activeAsset.value.id);
                    await loadAssets(currentPage.value);
                }
            } catch (err) {
                showToast('设置失败', 'error');
            }
        };

        const handleDeleteImage = async (imageId) => {
            if (!confirm('确定要删除此图片吗？') || !activeAsset.value) return;
            try {
                const res = await fetch(`/api/assets/${encodeURIComponent(activeAsset.value.id)}/images/${imageId}`, {
                    method: 'DELETE',
                });
                if (res.ok) {
                    showToast('图片已删除');
                    await openDetail(activeAsset.value.id);
                    await loadAssets(currentPage.value);
                    await loadStats();
                }
            } catch (err) {
                showToast('删除失败', 'error');
            }
        };

        const handleDeleteAsset = async (assetId) => {
            if (!confirm(`确定要彻底删除资产【${assetId}】及其所有图片吗？此操作无法撤销！`)) return;
            try {
                const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}`, {
                    method: 'DELETE',
                });
                if (res.ok) {
                    showToast('资产已成功删除');
                    showDetailModal.value = false;
                    await loadAssets(currentPage.value);
                    await loadStats();
                    await loadLocations();
                }
            } catch (err) {
                showToast('删除失败', 'error');
            }
        };

        // Open Lightbox
        const openLightbox = (url) => {
            lightboxImageUrl.value = url;
            showLightbox.value = true;
        };

        // -------------------------------------------------------------
        // Asset Tag / QR Code Generation & Printing
        // -------------------------------------------------------------
        const openPrintLabel = (asset) => {
            labelAsset.value = asset;
            showLabelModal.value = true;
            nextTick(() => {
                const container = document.getElementById('label-qrcode');
                if (container) {
                    container.innerHTML = '';
                    // URL encoded to asset detail or simple ID
                    const qrText = `${window.location.origin}/#asset=${asset.id}`;
                    new QRCode(container, {
                        text: qrText,
                        width: 130,
                        height: 130,
                        colorDark: "#0f172a",
                        colorLight: "#ffffff",
                        correctLevel: QRCode.CorrectLevel.H,
                    });
                }
                refreshIcons();
            });
        };

        const triggerPrint = () => {
            window.print();
        };

        // -------------------------------------------------------------
        // Barcode / QR Code Scanner
        // -------------------------------------------------------------
        const openScanner = () => {
            showScannerModal.value = true;
            nextTick(() => {
                if (!window.Html5Qrcode) {
                    showToast('扫描器库未准备好', 'error');
                    return;
                }
                html5QrCodeScanner = new Html5Qrcode("interactive-qr-scanner");
                const config = { fps: 10, qrbox: { width: 250, height: 250 } };
                html5QrCodeScanner.start(
                    { facingMode: "environment" },
                    config,
                    (decodedText) => {
                        // Success callback
                        stopScanner();
                        handleScannedText(decodedText);
                    },
                    (errorMessage) => {
                        // Scanning frame error, ignore
                    }
                ).catch(err => {
                    console.error("Camera access error:", err);
                    showToast("无法打开摄像头，请确保已授予摄像头权限并使用 HTTPS 访问", "error");
                });
            });
        };

        const stopScanner = () => {
            if (html5QrCodeScanner) {
                html5QrCodeScanner.stop().then(() => {
                    html5QrCodeScanner.clear();
                    html5QrCodeScanner = null;
                }).catch(console.error);
            }
            showScannerModal.value = false;
        };

        const handleScannedText = async (text) => {
            let matchId = text.trim();
            if (text.includes('#asset=')) {
                matchId = text.split('#asset=')[1].trim();
            }
            showToast(`已识别编号: ${matchId}`);
            searchQuery.value = matchId;
            await loadAssets();
            // If exact asset found, open it directly!
            const found = assets.value.find(a => a.id.toLowerCase() === matchId.toLowerCase());
            if (found) {
                openDetail(found.id);
            } else {
                if (confirm(`已识别资产编号【${matchId}】，但系统中暂无记录。是否立即以此编号登记新资产？`)) {
                    openAddModal();
                    assetForm.value.id = matchId;
                }
            }
        };

        const handleScannerFileUpload = async (event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            showToast('正在分析图片中的资产编号与标签...');
            try {
                const formData = new FormData();
                formData.append('file', file);
                const res = await fetch('/api/assets/recognize-id', {
                    method: 'POST',
                    body: formData,
                });
                if (res.ok) {
                    const data = await res.json();
                    if (data.best_id) {
                        stopScanner();
                        await handleScannedText(data.best_id);
                    } else {
                        showToast('未能识别出图片中的编号或二维码', 'error');
                    }
                }
            } catch (e) {
                showToast('识别失败: ' + e.message, 'error');
            } finally {
                event.target.value = '';
            }
        };

        // Export to CSV
        const exportCsv = () => {
            window.location.href = '/api/assets/export/csv';
        };

        // Quick select location from chip
        const filterByLocation = (loc) => {
            selectedLocation.value = selectedLocation.value === loc ? '' : loc;
            loadAssets(1);
        };

        // Quick fill location in form
        const setFormLocation = (loc) => {
            assetForm.value.location = loc;
        };

        onMounted(() => {
            checkAuthStatus();
        });

        return {
            authStatus,
            isAuthChecking,
            isSecureContext,
            setupForm,
            loginForm,
            authLoading,
            authError,
            handleInitialSetup,
            handlePasskeyLogin,
            handleLogout,
            showUserModal,
            userPasskeys,
            newDeviceName,
            isAddingPasskey,
            openUserModal,
            handleAddPasskey,
            handleDeletePasskey,
            assets,
            totalAssets,
            currentPage,
            pageSize,
            totalPages,
            isLoadingAssets,
            viewMode,
            searchQuery,
            selectedLocation,
            selectedCategory,
            selectedStatus,
            locationsList,
            stats,
            loadAssets,
            showAssetModal,
            isEditing,
            assetForm,
            pendingImages,
            isSavingAsset,
            generateAssetId,
            openAddModal,
            openEditModal,
            handleFilesSelected,
            handleDrop,
            handlePaste,
            removePendingImage,
            saveAsset,
            isRecognizingId,
            idCandidates,
            recognizeIdFromFile,
            triggerManualRecognize,
            handleScannerFileUpload,
            showDetailModal,
            activeAsset,
            activeImageIndex,
            isUploadingMoreImages,
            openDetail,
            handleUploadMoreImages,
            handleSetPrimaryImage,
            handleDeleteImage,
            handleDeleteAsset,
            showLightbox,
            lightboxImageUrl,
            openLightbox,
            showLabelModal,
            labelAsset,
            openPrintLabel,
            triggerPrint,
            showScannerModal,
            openScanner,
            stopScanner,
            exportCsv,
            filterByLocation,
            setFormLocation,
            toast,
            refreshIcons,
        };
    }
});

app.mount('#app');

