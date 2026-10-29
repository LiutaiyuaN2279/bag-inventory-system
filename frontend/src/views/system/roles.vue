<template>
  <div class="page">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><Key /></el-icon>角色权限</h2>
        <div class="ph-desc">维护角色及其功能权限，权限按模块分组配置 · 共 <b>{{ total }}</b> 个角色</div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Refresh" @click="fetchList">刷新</el-button>
        <el-button type="primary" :icon="Plus" v-permission="'system:role:add'" @click="onAdd">新增角色</el-button>
      </div>
    </div>

    <!-- 列表卡：筛选条 + 表格 + 分页，卡片撑满内容区，表格区内部滚动 -->
    <el-card shadow="never" class="card-fill">
      <div class="toolbar">
        <el-form :inline="true" :model="query" class="tb-left">
          <el-form-item label="关键字">
            <el-input v-model="query.keyword" placeholder="角色编码 / 名称" clearable style="width: 220px" @keyup.enter="onSearch" />
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
        <el-table-column prop="role_code" label="角色编码" min-width="140" sortable="custom">
          <template #default="{ row }">
            <el-tag size="small" type="info" effect="plain">{{ row.role_code }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="role_name" label="角色名称" min-width="200" sortable="custom" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="200" show-overflow-tooltip sortable="custom" />
        <el-table-column prop="user_count" label="用户数" width="100" sortable="custom" align="right" class-name="col-num" />
        <el-table-column prop="perm_count" label="权限数" width="110" sortable="custom" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.perm_count ? 'success' : 'info'">{{ row.perm_count || 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" v-permission="'system:role:edit'" @click="openPermDialog(row)">配置权限</el-button>
            <el-button link type="primary" v-permission="'system:role:edit'" @click="onEdit(row)">编辑</el-button>
            <el-button
              link
              type="danger"
              v-permission="'system:role:delete'"
              :disabled="row.role_code === 'admin'"
              :title="row.role_code === 'admin' ? '内置管理员角色不可删除' : ''"
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

    <!-- 配置权限弹窗 -->
    <el-dialog v-model="permDialog.visible" :title="`配置权限 - ${permDialog.roleName}`" width="640px">
      <div class="perm-toolbar">
        <el-button size="small" @click="toggleExpand(true)">展开全部</el-button>
        <el-button size="small" @click="toggleExpand(false)">折叠全部</el-button>
        <el-button size="small" type="primary" plain @click="onCheckAll">全选</el-button>
        <el-button size="small" type="primary" plain @click="onInvert">反选</el-button>
        <span class="perm-stat">已选 {{ checkedCount }} / {{ leafCount }} 项权限</span>
      </div>
      <div v-loading="permDialog.loading" class="perm-tree">
        <el-tree
          ref="treeRef"
          :key="treeKey"
          :data="permTree"
          show-checkbox
          node-key="id"
          :default-expand-all="expandAll"
          :props="{ label: 'label', children: 'children' }"
          @check="refreshCheckedCount"
        >
          <template #default="{ data }">
            <span :class="['tree-node', data.children ? 'tree-node--group' : '']">
              <el-icon class="tree-icon"><Folder v-if="data.children" /><Document v-else /></el-icon>
              <span>{{ data.label }}</span>
            </span>
          </template>
        </el-tree>
      </div>
      <template #footer>
        <el-button @click="permDialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="permDialog.submitting" @click="onSavePermissions">保 存</el-button>
      </template>
    </el-dialog>

    <!-- 新增 / 编辑角色弹窗 -->
    <el-dialog v-model="roleDialog.visible" :title="roleDialog.isEdit ? '编辑角色' : '新增角色'" width="480px">
      <el-form ref="roleFormRef" :model="roleForm" :rules="roleRules" label-width="90px">
        <el-form-item label="角色编码" prop="role_code">
          <el-input v-model="roleForm.role_code" :disabled="roleDialog.isEdit" placeholder="如 buyer，创建后不可修改" />
        </el-form-item>
        <el-form-item label="角色名称" prop="role_name">
          <el-input v-model="roleForm.role_name" placeholder="如 采购员" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="roleForm.remark" type="textarea" :rows="2" placeholder="角色职责说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialog.visible = false">取 消</el-button>
        <el-button type="primary" :loading="roleSubmitting" @click="onSubmitRole">确 定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { Search, Refresh, Plus, Key, Folder, Document } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { roleApi } from '@/api/user'
import { useSort } from '@/composables/useSort'
import { useBatch } from '@/composables/useBatch'
import { exportRows } from '@/utils/exportRows'
import SortChips from '@/components/SortChips.vue'
import BatchBar from '@/components/BatchBar.vue'

// 权限模块中文名与权限树构造统一放在 utils/permTree.js，供角色/用户两处复用
import { buildPermTree } from '@/utils/permTree'

const query = reactive({ page: 1, page_size: 20, keyword: '' })
const list = ref([])
const total = ref(0)
const loading = ref(false)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / query.page_size)))

async function fetchList() {
  loading.value = true
  try {
    const res = await roleApi.list({ ...query })
    list.value = res.list || []
    total.value = res.total || 0
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出，这里兜底避免未捕获异常
  } finally { loading.value = false }
}

const { onSortChange, sortRules, removeSort, clearSort } = useSort(query, fetchList)

// ---- 批量操作 ----
const batch = useBatch({ fetchList })
const batchActions = [
  { key: 'delete', label: '批量删除', type: 'danger', perm: 'system:role:delete' },
  { key: 'export', label: '导出选中', perm: 'system:role:list' }
]
const exportColumns = [
  { prop: 'role_code', label: '角色编码' },
  { prop: 'role_name', label: '角色名称' },
  { prop: 'remark', label: '备注' },
  { prop: 'user_count', label: '用户数' },
  { prop: 'perm_count', label: '权限数' }
]

async function onBatchAction(key) {
  if (key === 'export') {
    exportRows(batch.selected.value, exportColumns, '角色清单')
    return
  }
  const n = batch.count.value
  const confirm = `确认删除选中的 ${n} 个角色？删除后不可恢复。内置管理员角色 admin、以及仍被用户引用的角色会被自动跳过，失败原因将逐条列出。`
  await batch.run(roleApi.batch, key, { label: '批量删除', confirm })
}

function onSearch() { query.page = 1; batch.clearSelection(); fetchList() }
function onReset() { query.keyword = ''; onSearch() }

// ---------- 权限树 ----------
const permList = ref([])        // 权限清单（只拉一次并缓存）
const permTree = ref([])        // 按 module 分组的树数据
const leafCount = ref(0)
let leafIdSet = new Set()       // 叶子（真实权限）id 集合，用于过滤父节点
let permApiUnsupported = false  // 后端未实现「读取角色权限」接口时，只尝试一次

const permDialog = reactive({ visible: false, loading: false, roleId: null, roleName: '', submitting: false })
const treeRef = ref()
const treeKey = ref(0)
const expandAll = ref(true)
const checkedCount = ref(0)

// 把权限数组按 module 分组为「模块父节点 + 权限叶子节点」（实现见 utils/permTree.js）
function buildTree(perms) {
  const { nodes, leaves } = buildPermTree(perms)
  leafIdSet = leaves
  leafCount.value = leaves.size
  checkedCount.value = 0
  return nodes
}

async function loadPermissions() {
  if (permList.value.length) return true
  try {
    const res = await roleApi.permissions()
    permList.value = Array.isArray(res) ? res : (res?.list || [])
    permTree.value = buildTree(permList.value)
    return true
  } catch (e) {
    permList.value = [] // 提示已由拦截器给出
    return false
  }
}

// 读取角色已有权限 id：优先列表行自带的 perm_ids，其次行内 permissions，最后回退专用接口
async function resolveOwnedPermIds(row) {
  if (Array.isArray(row.perm_ids)) return row.perm_ids.filter((id) => leafIdSet.has(id))
  if (Array.isArray(row.permissions)) {
    const codes = row.permissions.map((p) => (typeof p === 'string' ? p : p.perm_code)).filter(Boolean)
    return permList.value.filter((p) => codes.includes(p.perm_code)).map((p) => p.id)
  }
  if (permApiUnsupported) return []
  try {
    const res = await roleApi.permissionsOf(row.id)
    const raw = Array.isArray(res) ? res : (res?.perm_ids || res?.list || [])
    return raw.map((v) => (v && typeof v === 'object' ? v.id : v)).filter((id) => leafIdSet.has(id))
  } catch (e) {
    permApiUnsupported = true // 后端未实现该接口：后续不再重复请求，静默按“未配置”处理
    return []
  }
}

// 当前已勾选的叶子权限 id
function currentLeafChecked() {
  const keys = treeRef.value ? treeRef.value.getCheckedKeys() : []
  return keys.filter((k) => leafIdSet.has(k))
}
function refreshCheckedCount() { checkedCount.value = currentLeafChecked().length }

async function openPermDialog(row) {
  Object.assign(permDialog, { visible: true, loading: true, roleId: row.id, roleName: row.role_name })
  expandAll.value = true
  treeKey.value++ // 重建树以应用「展开全部」初始状态
  try {
    const ok = await loadPermissions()
    if (!ok) return
    const owned = await resolveOwnedPermIds(row)
    await nextTick()
    if (treeRef.value) treeRef.value.setCheckedKeys(owned)
    refreshCheckedCount()
  } finally {
    permDialog.loading = false
  }
}

// 展开 / 折叠：通过重建树 + 回填勾选实现（只用公开 API）
async function toggleExpand(expand) {
  const keep = currentLeafChecked()
  expandAll.value = expand
  treeKey.value++
  await nextTick()
  if (treeRef.value && keep.length) treeRef.value.setCheckedKeys(keep)
  refreshCheckedCount()
}
function onCheckAll() {
  if (!treeRef.value) return
  treeRef.value.setCheckedKeys([...leafIdSet])
  refreshCheckedCount()
}
function onInvert() {
  if (!treeRef.value) return
  const now = new Set(currentLeafChecked())
  const next = [...leafIdSet].filter((id) => !now.has(id))
  treeRef.value.setCheckedKeys(next)
  refreshCheckedCount()
}

async function onSavePermissions() {
  if (!treeRef.value) return
  // 全选节点 + 半选父节点合并后，只提交叶子（真实权限）id
  const merged = [...treeRef.value.getCheckedKeys(), ...treeRef.value.getHalfCheckedKeys()]
  const permIds = [...new Set(merged)].filter((id) => leafIdSet.has(id))
  permDialog.submitting = true
  try {
    await roleApi.setPermissions(permDialog.roleId, { perm_ids: permIds })
    ElMessage.success('权限保存成功')
    permDialog.visible = false
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  } finally { permDialog.submitting = false }
}

// ---------- 角色新增 / 编辑 ----------
const roleDialog = reactive({ visible: false, isEdit: false })
const roleSubmitting = ref(false)
const roleFormRef = ref()
const roleForm = reactive({ id: null, role_code: '', role_name: '', remark: '' })
const roleRules = {
  role_code: [{ required: true, message: '请输入角色编码', trigger: 'blur' }],
  role_name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }]
}

function resetRoleForm() {
  Object.assign(roleForm, { id: null, role_code: '', role_name: '', remark: '' })
  if (roleFormRef.value) roleFormRef.value.clearValidate()
}
function onAdd() { resetRoleForm(); roleDialog.isEdit = false; roleDialog.visible = true }
function onEdit(row) {
  resetRoleForm()
  Object.assign(roleForm, { id: row.id, role_code: row.role_code, role_name: row.role_name, remark: row.remark || '' })
  roleDialog.isEdit = true
  roleDialog.visible = true
}

async function onSubmitRole() {
  try {
    await roleFormRef.value.validate()
  } catch (e) {
    return // 校验不通过，静默返回（不要抛出未捕获的 Promise 异常）
  }
  roleSubmitting.value = true
  try {
    const payload = { role_code: roleForm.role_code, role_name: roleForm.role_name, remark: roleForm.remark }
    if (roleDialog.isEdit) {
      await roleApi.update(roleForm.id, payload)
      ElMessage.success('修改成功')
    } else {
      await roleApi.create(payload)
      ElMessage.success('新增成功')
    }
    roleDialog.visible = false
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  } finally { roleSubmitting.value = false }
}

async function onDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除角色「${row.role_name}」？删除后该角色的权限配置将一并解除`,
      '提示',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户点击取消 / 关闭，静默返回
  }
  try {
    await roleApi.remove(row.id)
    ElMessage.success('删除成功')
    fetchList()
  } catch (e) {
    // 请求失败提示已由 request 拦截器统一给出
  }
}

onMounted(fetchList)
</script>

<style scoped>
.perm-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.perm-stat { margin-left: auto; font-size: 12px; color: var(--text-3); }
.perm-tree {
  max-height: 46vh; overflow: auto;
  border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; background: #fbfcfe;
}
.tree-node { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.tree-node--group { font-weight: 600; color: var(--text-1); }
.tree-icon { font-size: 14px; color: var(--brand); }
</style>
