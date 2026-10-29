<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><User /></el-icon>用户管理</h2>
        <div class="ph-desc">维护系统登录账号与角色授权 · 共 <b>{{ total }}</b> 个用户</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'system:user:add'" @click="onAdd">新增用户</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页，卡片撑满内容区，表格区内部滚动 -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="用户名 / 姓名" clearable style="width: 220px" @keyup.enter="onSearch" />
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="query.status" placeholder="全部" clearable style="width: 130px">
              <el-option label="启用" :value="true" />
              <el-option label="停用" :value="false" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Search" @click="onSearch">查询</el-button>
            <el-button :icon="Refresh" @click="onReset">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="tb-right">
          <SortChips :rules="sortRules" @remove="removeSort" @clear="clearSort" />
        </div>
      </div>

      <!-- 批量操作条：勾选后才出现，不占固定高度 -->
      <BatchBar :batch="batch" :actions="batchActions" @action="onBatchAction" />

      <div class="table-wrap">
      <el-table :ref="batch.bindTable" :data="list" :row-key="(row) => row.id" v-loading="loading" border stripe
        @sort-change="onSortChange" @selection-change="batch.onSelectionChange">
        <el-table-column type="selection" width="50" align="center" reserve-selection />
        <el-table-column type="index" label="#" width="55" align="center" />
        <el-table-column prop="username" label="用户名" width="150" sortable="custom" show-overflow-tooltip />
        <el-table-column prop="real_name" label="姓名" min-width="170" sortable="custom" show-overflow-tooltip />
        <el-table-column label="角色" width="180">
          <template #default="{ row }">
            <el-tag v-for="code in row.roles || []" :key="code" size="small" effect="plain" class="role-tag">
              {{ roleName(code) }}
            </el-tag>
            <span v-if="!(row.roles || []).length" class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90" align="center" sortable="custom">
          <template #default="{ row }">
            <el-tag :type="row.status ? 'success' : 'info'" size="small">{{ row.status ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="200" sortable="custom">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="310" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" v-permission="'system:user:edit'" @click="onEdit(row)">编辑</el-button>
            <el-button link type="success" v-permission="'system:user:perm'" @click="onPerm(row)">
              配置权限<span v-if="row.override_count" class="ov-dot">·{{ row.override_count }}</span>
            </el-button>
            <el-button link type="warning" v-permission="'system:user:edit'" @click="onResetPwd(row)">重置密码</el-button>
            <el-button
              link
              type="danger"
              v-permission="'system:user:delete'"
              :disabled="isProtected(row)"
              :title="isProtected(row) ? '内置管理员与当前登录用户不可删除' : ''"
              @click="onDelete(row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>

      <div class="pager">
        <span class="hint">共 <b>{{ total }}</b> 条 · 第 {{ query.page }} / {{ pageCount }} 页</span>
        <el-pagination background layout="sizes, prev, pager, next" :total="total"
          v-model:current-page="query.page" v-model:page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]" @current-change="fetchList" @size-change="fetchList" />
      </div>
    </el-card>

    <!-- 新增 / 编辑弹窗 -->
    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑用户' : '新增用户'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="dialog.isEdit" placeholder="登录账号，创建后不可修改" />
        </el-form-item>
        <el-form-item v-if="!dialog.isEdit" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="姓名" prop="real_name">
          <el-input v-model="form.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple clearable placeholder="请选择角色" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.id" :label="r.role_name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">确 定</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog v-model="pwdDialog.visible" title="重置密码" width="460px">
      <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px"
        :title="`即将重置用户「${pwdDialog.realName || pwdDialog.username}」的登录密码`" />
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="90px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="pwdForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password placeholder="请再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="pwdSubmitting" @click="onResetPwdSubmit">确 定</el-button>
      </template>
    </el-dialog>

    <!-- 用户级权限配置弹窗：角色权限之上「额外授予 / 明确禁用」 -->
    <el-dialog v-model="permDialog.visible" :title="`配置权限 · ${permDialog.realName || permDialog.username}`" width="760px" top="6vh">
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
        <template #title>
          有效权限 = 角色权限 ∪ 额外授予 − 明确禁用。勾选状态即该用户最终生效的权限；
          <b>取消勾选角色已有的权限 = 单独禁用</b>（仅对该用户生效，不影响所属角色）。
        </template>
      </el-alert>

      <div class="perm-bar">
        <el-tag size="small" type="info">角色：{{ permDialog.roleNames || '未分配' }}</el-tag>
        <el-tag size="small" type="success">额外授予 {{ grantCount }} 项</el-tag>
        <el-tag size="small" type="danger">单独禁用 {{ denyCount }} 项</el-tag>
        <span class="muted">已选 {{ checkedCount }} / {{ leafTotal }} 项</span>
        <div class="perm-bar-right">
          <el-button size="small" :icon="Refresh" @click="onPermReset" :disabled="!hasOverride">还原为角色权限</el-button>
          <el-button size="small" type="primary" plain @click="onCheckAll">全选</el-button>
          <el-button size="small" @click="onInvert">反选</el-button>
        </div>
      </div>

      <div v-loading="permDialog.loading" class="perm-tree">
        <el-tree
          v-if="permDialog.visible"
          ref="permTreeRef"
          :key="permTreeKey"
          :data="permTree"
          node-key="id"
          show-checkbox
          :default-expand-all="true"
          @check="refreshChecked"
        />
      </div>

      <template #footer>
        <el-button @click="permDialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="permDialog.submitting" @click="onSavePerm">保 存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, User } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { userApi, roleApi } from '@/api/user'
import { useUserStore } from '@/store/user'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import { buildPermTree } from '@/utils/permTree'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

const userStore = useUserStore()

const query = reactive({ page: 1, page_size: 20, keyword: '', status: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const roleOptions = ref([]) // 角色下拉选项（全量）
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

async function fetchList() {
  loading.value = true
  try {
    const params = { ...query }
    // 未选择状态时不传该参数，避免后端布尔校验失败
    if (params.status === '') delete params.status
    const res = await userApi.list(params)
    list.value = res.list || []
    total.value = res.total || 0
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出，这里兜底避免未捕获异常
  } finally { loading.value = false }
}

// 角色选择器需要全量角色，分页接口按大页取一次
async function fetchRoles() {
  try {
    const res = await roleApi.list({ page: 1, page_size: 100 })
    roleOptions.value = res.list || []
  } catch (e) {
    roleOptions.value = []
  }
}

const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
const batchActions = [
  { key: 'enable', label: '批量启用', perm: 'system:user:edit' },
  { key: 'disable', label: '批量停用', perm: 'system:user:edit' },
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'system:user:delete' },
  { key: 'export', label: '导出选中', perm: 'system:user:list' }
]
const exportColumns = [
  { prop: 'username', label: '用户名' },
  { prop: 'real_name', label: '姓名' },
  { prop: 'roles', label: '角色', formatter: (r) => (r.roles || []).map(roleName).join('、') || '未分配' },
  { prop: 'status', label: '状态', formatter: (r) => (r.status ? '启用' : '停用') },
  { prop: 'created_at', label: '创建时间', formatter: (r) => fmtTime(r.created_at) }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '用户清单')
    return
  }
  const n = batch.count.value
  const labels = { enable: '批量启用', disable: '批量停用', delete: '批量删除' }
  const label = labels[key] || '批量操作'
  let confirm = `确认对选中的 ${n} 个用户执行「${label.slice(2)}」？`
  if (key === 'delete') {
    confirm = `确认删除选中的 ${n} 个用户？删除后不可恢复。内置管理员 admin 与当前登录账号会被自动跳过，失败原因将逐条列出。`
  } else if (key === 'disable') {
    confirm = `确认停用选中的 ${n} 个用户？停用后该账号将无法登录。内置管理员 admin 会被自动跳过。`
  }
  await batch.run(userApi.batch, key, { label, confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; query.status = ''; onSearch() }

// 时间格式化：ISO 字符串转「YYYY-MM-DD HH:mm:ss」
function fmtTime(v) { return v ? String(v).replace('T', ' ').slice(0, 19) : '-' }
// 角色编码 → 角色名称（角色列表未加载时退回显示编码）
function roleName(code) {
  const hit = roleOptions.value.find((r) => r.role_code === code)
  return hit ? hit.role_name : code
}
// 是否为当前登录用户
function isSelf(row) {
  const u = userStore.userInfo
  return !!u && (row.id === u.id || row.username === u.username)
}
// admin 与当前登录用户禁止删除
function isProtected(row) { return row.username === 'admin' || isSelf(row) }

const dialog = reactive({ visible: false, isEdit: false })
const submitting = ref(false)
const formRef = ref()
const form = reactive({ id: null, username: '', password: '', real_name: '', status: true, role_ids: [] })
const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { max: 32, message: '最长 32 个字符', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 32, message: '长度 6-32 个字符', trigger: 'blur' }
  ],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }]
}

function resetForm() {
  Object.assign(form, { id: null, username: '', password: '', real_name: '', status: true, role_ids: [] })
  if (formRef.value) formRef.value.clearValidate()
}
function onAdd() { resetForm(); dialog.isEdit = false; dialog.visible = true }
function onEdit(row) {
  resetForm()
  Object.assign(form, {
    id: row.id,
    username: row.username,
    password: '',
    real_name: row.real_name,
    status: !!row.status,
    role_ids: Array.isArray(row.role_ids) ? [...row.role_ids] : resolveRoleIds(row.roles)
  })
  dialog.isEdit = true
  dialog.visible = true
}
// 行内未返回 role_ids 时，用角色编码反查 id 兜底
function resolveRoleIds(codes) {
  return (codes || [])
    .map((c) => (roleOptions.value.find((r) => r.role_code === c) || {}).id)
    .filter((v) => v !== undefined && v !== null)
}

async function onSubmit() {
  try {
    await formRef.value.validate()
  } catch (e) {
    return // 校验不通过，静默返回（不要抛出未捕获的 Promise 异常）
  }
  submitting.value = true
  try {
    if (dialog.isEdit) {
      await userApi.update(form.id, { real_name: form.real_name, status: form.status, role_ids: form.role_ids })
      ElMessage.success('修改成功')
    } else {
      await userApi.create({
        username: form.username,
        password: form.password,
        real_name: form.real_name,
        status: form.status,
        role_ids: form.role_ids
      })
      ElMessage.success('新增成功')
    }
    dialog.visible = false
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  } finally { submitting.value = false }
}

// ---------- 重置密码 ----------
const pwdDialog = reactive({ visible: false, id: null, username: '', realName: '' })
const pwdSubmitting = ref(false)
const pwdFormRef = ref()
const pwdForm = reactive({ password: '', confirm: '' })
const pwdRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, max: 32, message: '长度 6-32 个字符', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) => {
        if (value === pwdForm.password) callback()
        else callback(new Error('两次输入的密码不一致'))
      },
      trigger: 'blur'
    }
  ]
}
function onResetPwd(row) {
  Object.assign(pwdForm, { password: '', confirm: '' })
  Object.assign(pwdDialog, { visible: true, id: row.id, username: row.username, realName: row.real_name })
  if (pwdFormRef.value) pwdFormRef.value.clearValidate()
}
async function onResetPwdSubmit() {
  try {
    await pwdFormRef.value.validate()
  } catch (e) {
    return // 校验不通过，静默返回
  }
  pwdSubmitting.value = true
  try {
    await userApi.resetPassword(pwdDialog.id, { password: pwdForm.password })
    ElMessage.success('密码重置成功')
    pwdDialog.visible = false
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  } finally { pwdSubmitting.value = false }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.real_name || row.username}」？删除后不可恢复`,
      '提示',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户点击取消 / 关闭，静默返回
  }
  try {
    await userApi.remove(row.id)
    ElMessage.success('删除成功')
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  }
}

// ---------- 用户级权限配置（角色权限之上「额外授予 / 明确禁用」） ----------
const permDialog = reactive({
  visible: false, loading: false, submitting: false,
  userId: null, username: '', realName: '', roleNames: ''
})
const permList = ref([])          // 全量权限清单（只拉一次并缓存）
const permTree = ref([])          // 按模块分组的权限树
const permLeaves = ref([])        // 全部叶子（真实权限）id
const permTreeKey = ref(0)        // 自增以重建树，确保初始展开/勾选生效
const permTreeRef = ref()
const roleGrantedIds = ref(new Set())  // 该用户所属角色已授予的权限 id
const grantIds = ref(new Set())        // 额外授予
const denyIds = ref(new Set())         // 明确禁用
const checkedIds = ref([])             // 当前树上勾选的叶子 id

const leafTotal = computed(() => permLeaves.value.length)
const checkedCount = computed(() => checkedIds.value.length)
const grantCount = computed(() => grantIds.value.size)
const denyCount = computed(() => denyIds.value.size)
const hasOverride = computed(() => grantCount.value > 0 || denyCount.value > 0)

async function loadPermList() {
  if (permList.value.length) return true
  try {
    const res = await roleApi.permissions()
    permList.value = Array.isArray(res) ? res : (res?.list || [])
    const { nodes, leaves } = buildPermTree(permList.value)
    permTree.value = nodes
    permLeaves.value = [...leaves]
    return true
  } catch (e) {
    permList.value = []
    return false
  }
}

// 当前勾选（过滤掉父节点分组 id）
function currentLeafChecked() {
  const keys = permTreeRef.value ? permTreeRef.value.getCheckedKeys() : []
  return keys.filter((k) => typeof k === 'number')
}

// 由「勾选状态 + 角色权限」反推覆盖项：
// 勾了而角色没有 → grant；角色有却没勾 → deny
function deriveOverrides() {
  const checked = new Set(checkedIds.value)
  const grants = new Set()
  const denies = new Set()
  checked.forEach((id) => { if (!roleGrantedIds.value.has(id)) grants.add(id) })
  roleGrantedIds.value.forEach((id) => { if (!checked.has(id)) denies.add(id) })
  grantIds.value = grants
  denyIds.value = denies
}

function refreshChecked() {
  checkedIds.value = currentLeafChecked()
  deriveOverrides()
}

async function onPerm(row) {
  Object.assign(permDialog, {
    visible: true, loading: true, submitting: false,
    userId: row.id, username: row.username, realName: row.real_name,
    roleNames: (row.roles || []).map(roleName).join('、')
  })
  grantIds.value = new Set()
  denyIds.value = new Set()
  checkedIds.value = []
  roleGrantedIds.value = new Set()
  permTreeKey.value++
  const ok = await loadPermList()
  if (!ok) { permDialog.loading = false; return }
  try {
    const res = await userApi.permissionsOf(row.id)
    roleGrantedIds.value = new Set(res.role_perm_ids || [])
    grantIds.value = new Set(res.grant_ids || [])
    denyIds.value = new Set(res.deny_ids || [])
  } catch (e) {
    // 提示已由拦截器给出；失败时按「无覆盖」处理，不影响角色权限展示
  }
  // 树勾选 = 有效权限 = (角色权限 ∪ grant) − deny
  const effective = new Set(roleGrantedIds.value)
  grantIds.value.forEach((id) => effective.add(id))
  denyIds.value.forEach((id) => effective.delete(id))
  const checked = permLeaves.value.filter((id) => effective.has(id))
  permTreeKey.value++
  await nextTick()
  if (permTreeRef.value) permTreeRef.value.setCheckedKeys(checked)
  checkedIds.value = checked
  permDialog.loading = false
}

// 还原为角色权限（清空全部覆盖项）
async function onPermReset() {
  if (!permTreeRef.value) return
  const checked = permLeaves.value.filter((id) => roleGrantedIds.value.has(id))
  permTreeRef.value.setCheckedKeys(checked)
  checkedIds.value = checked
  grantIds.value = new Set()
  denyIds.value = new Set()
}

function onCheckAll() {
  if (!permTreeRef.value) return
  permTreeRef.value.setCheckedKeys([...permLeaves.value])
  refreshChecked()
}

function onInvert() {
  if (!permTreeRef.value) return
  const checked = new Set(currentLeafChecked())
  const next = permLeaves.value.filter((id) => !checked.has(id))
  permTreeRef.value.setCheckedKeys(next)
  checkedIds.value = next
  deriveOverrides()
}

async function onSavePerm() {
  refreshChecked()
  const items = [
    ...[...grantIds.value].map((id) => ({ perm_id: id, effect: 'grant' })),
    ...[...denyIds.value].map((id) => ({ perm_id: id, effect: 'deny' }))
  ]
  permDialog.submitting = true
  try {
    await userApi.setPermissions(permDialog.userId, { items })
    ElMessage.success(`已保存：额外授予 ${grantIds.value.size} 项，单独禁用 ${denyIds.value.size} 项`)
    permDialog.visible = false
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  } finally { permDialog.submitting = false }
}

onMounted(() => { fetchRoles(); fetchList() })
</script>

<style scoped>
.role-tag { margin-right: 4px; }
.muted { color: var(--text-3); font-size: 12px; }
.ov-dot { margin-left: 2px; font-size: 11px; opacity: .85; }

.perm-bar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; margin-bottom: 10px;
  background: var(--bg-2, #f7f9fc); border-radius: 6px;
}
.perm-bar-right { margin-left: auto; display: flex; gap: 8px; }
.perm-tree {
  max-height: 52vh; overflow: auto;
  border: 1px solid var(--border-1, #e6eaf2); border-radius: 6px;
  padding: 8px 10px;
}
</style>
