<template>
  <div class="page rmb-edit">
    <!-- 页头：标题 + 说明 + 主操作 -->
    <div class="page-head">
      <div>
        <h2 class="ph-title"><el-icon><EditPen /></el-icon>{{ isEdit ? '修改报销单' : '填写报销单' }}</h2>
        <div class="ph-desc">
          填写报销信息并上传票据，AI 识别后核对票据字段，确认保存即可提交合规判读
          <template v-if="savedInfo">· 已保存单号 <b>{{ savedInfo.bill_no }}</b></template>
        </div>
      </div>
      <div class="ph-actions">
        <el-button :icon="Back" @click="goBack">返回列表</el-button>
        <el-button v-if="savedInfo" type="primary" plain :icon="CircleCheck"
                   v-permission="'reimburse:check:run'" @click="goCompliance">提交 AI 合规判读</el-button>
        <el-button type="primary" :icon="Check" :loading="saving" @click="onSave">确认保存</el-button>
      </div>
    </div>

    <!-- 保存成功提示条：单号 + 进入判读 -->
    <el-alert v-if="savedInfo" class="saved-bar" type="success" :closable="false" show-icon
              :title="`报销单已保存，单号 ${savedInfo.bill_no}`"
              description="下一步请提交 AI 合规判读；也可先返回列表稍后再判读。" />

    <div class="edit-body">
      <!-- ================= 左：表单主体 ================= -->
      <div class="edit-main">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="118px" label-position="right">
          <!-- (1) 基本信息 -->
          <el-card shadow="never" class="sec-card">
            <template #header>
              <div class="sec-head"><span class="sec-title">一、基本信息</span>
                <span class="sec-hint">带 <i class="req">*</i> 为必填项；报销日期取服务器当前日期，不可修改</span>
              </div>
            </template>
            <el-row :gutter="18">
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="报销日期">
                  <el-input :model-value="meta.today || ''" disabled placeholder="服务器当前日期">
                    <template #prefix><el-icon><Calendar /></el-icon></template>
                  </el-input>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="报销人" prop="employee_id">
                  <!-- 有制单权限的可选员工；普通报销人固定本人只读 -->
                  <el-select v-if="meta.can_choose_employee" v-model="form.employee_id" filterable
                             placeholder="请选择报销人" style="width: 100%" @change="onEmployeeChange">
                    <el-option v-for="e in meta.employees || []" :key="e.id"
                               :label="`${e.name}（${e.department_name || '未分配部门'}）`" :value="e.id" />
                  </el-select>
                  <el-input v-else :model-value="currentEmployeeName" disabled placeholder="本人" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="部门">
                  <el-input :model-value="departmentName" disabled placeholder="随报销人自动带出" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="费用类型" prop="expense_type_id">
                  <el-select v-model="form.expense_type_id" placeholder="请选择费用类型"
                             style="width: 100%" @change="onExpenseTypeChange">
                    <el-option v-for="t in meta.expense_types || []" :key="t.id" :label="t.name" :value="t.id" />
                  </el-select>
                  <div v-if="suggestedType" class="ai-type-hint">
                    <el-icon><MagicStick /></el-icon>
                    <span>AI 识别建议：<b>{{ suggestedType.name }}</b></span>
                    <el-button v-if="form.expense_type_id !== suggestedType.id" link type="primary"
                               class="ai-type-apply" @click="applySuggestedType(true)">采用</el-button>
                    <span v-else class="ai-type-done">已采用</span>
                  </div>
                  <div v-else-if="invoice.suggested_expense_type" class="ai-type-hint warn">
                    AI 建议「{{ invoice.suggested_expense_type }}」与系统费用类型不匹配，请手动选择
                  </div>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="费用发生日期" prop="occur_date">
                  <el-date-picker v-model="form.occur_date" type="date" value-format="YYYY-MM-DD"
                                  placeholder="选择费用发生日期" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="结算方式">
                  <el-select v-model="form.settlement_method_id" placeholder="请选择结算方式" clearable style="width: 100%">
                    <el-option v-for="s in meta.settlement_methods || []" :key="s.id" :label="s.name" :value="s.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="审批人姓名">
                  <el-select v-model="form.approver_name" filterable allow-create clearable
                             default-first-option placeholder="选择审批人（也可直接输入）"
                             style="width: 100%" @change="onApproverChange">
                    <el-option v-for="a in meta.approvers || []" :key="a.name"
                               :label="`${a.name}（${a.level}）`" :value="a.name" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="审批层级">
                  <el-select v-model="form.approver_level" placeholder="请选择审批层级" clearable style="width: 100%">
                    <el-option v-for="l in APPROVER_LEVELS" :key="l" :label="l" :value="l" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="报销事由">
                  <div class="reason-field">
                    <el-input v-model="form.reason" type="textarea" :rows="2" maxlength="200" show-word-limit
                              placeholder="简述本次报销的业务事由，如：10 月赴杭州参加箱包展会差旅费" />
                    <div class="reason-actions">
                      <span class="reason-tip">AI 会根据票据与已填信息生成，可再修改</span>
                      <el-button size="small" type="primary" plain :icon="MagicStick"
                                 :loading="reasonLoading" @click="onSuggestReason">AI 生成报销事由</el-button>
                    </div>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
          </el-card>

          <!-- (2) 差旅专项：仅当费用类型 special_info == '差旅' -->
          <el-card v-if="specialInfo === '差旅'" shadow="never" class="sec-card">
            <template #header>
              <div class="sec-head"><span class="sec-title">二、差旅专项信息</span>
                <span class="sec-hint">住宿标准与城市等级相关，超标须补填「特批与说明」</span>
              </div>
            </template>
            <el-row :gutter="18">
              <el-col :xs="24" :sm="12" :lg="8">
                <el-form-item label="出差地点">
                  <el-autocomplete v-model="form.travel_city" :fetch-suggestions="queryCity"
                                   placeholder="输入城市名，或从城市等级中选择" clearable style="width: 100%">
                    <template #default="{ item }">
                      <span>{{ item.value }}</span>
                      <span class="city-limit">{{ item.city_level }} · 住宿上限 {{ item.lodging_limit }} 元/晚</span>
                    </template>
                  </el-autocomplete>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="10">
                <el-form-item label="出差起止日期">
                  <el-date-picker v-model="travelRange" type="daterange" value-format="YYYY-MM-DD"
                                  range-separator="至" start-placeholder="出发日期" end-placeholder="返回日期"
                                  style="width: 100%" @change="onTravelRangeChange" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="6">
                <el-form-item label="住宿晚数">
                  <el-input-number v-model="form.nights" :min="0" :max="365" :precision="0"
                                   controls-position="right" style="width: 100%" @change="nightsManual = true" />
                </el-form-item>
              </el-col>
            </el-row>
            <div v-if="travelTip" class="inline-tip">
              <el-icon><InfoFilled /></el-icon><span>{{ travelTip }}</span>
            </div>
          </el-card>

          <!-- (3) 招待专项：仅当费用类型 special_info == '招待' -->
          <el-card v-if="specialInfo === '招待'" shadow="never" class="sec-card">
            <template #header>
              <div class="sec-head"><span class="sec-title">二、业务招待专项信息</span>
                <span class="sec-hint">人均标准由陪同人数与金额自动计算，周末 / 节假日招待须补填说明</span>
              </div>
            </template>
            <el-row :gutter="18">
              <el-col :xs="24" :sm="12" :lg="10">
                <el-form-item label="招待对象单位">
                  <el-input v-model="form.guest_company" placeholder="填写被招待单位名称" maxlength="64" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12" :lg="6">
                <el-form-item label="陪同人数">
                  <el-input-number v-model="form.guest_count" :min="0" :max="999" :precision="0"
                                   controls-position="right" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="24" :lg="8">
                <el-form-item label="人均金额">
                  <el-input :model-value="perCapitaText" disabled />
                </el-form-item>
              </el-col>
            </el-row>
          </el-card>

          <!-- (4) 特批与说明 -->
          <el-card shadow="never" class="sec-card">
            <template #header>
              <div class="sec-head"><span class="sec-title">{{ specialInfo === '无' ? '二' : '三' }}、特批与情况说明</span>
                <span class="sec-hint">存在超标、周末或节假日招待、无发票、跨年度报销等情形时须填写，否则可能判为不合规</span>
              </div>
            </template>
            <el-row :gutter="18">
              <el-col :xs="24" :sm="12">
                <el-form-item label="特批人及职务">
                  <el-input v-model="form.special_approver" placeholder="如：张总（总经理）" maxlength="64" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="情况说明">
                  <el-input v-model="form.explanation" type="textarea" :rows="3" maxlength="500" show-word-limit
                            placeholder="存在超标、周末或节假日招待、无发票、跨年度报销等情形时请填写，说明原因与特批依据" />
                </el-form-item>
              </el-col>
            </el-row>
          </el-card>
        </el-form>

        <!-- (5) 票据 -->
        <el-card shadow="never" class="sec-card">
          <template #header>
            <div class="sec-head">
              <span class="sec-title">{{ specialInfo === '无' ? '三' : '四' }}、票据信息</span>
              <span class="sec-hint">
                附发票时须上传票据原件（pdf / jpg / jpeg / png），由 AI 识别后核对；
                无发票时须手工填写报销金额
              </span>
            </div>
          </template>

          <el-row :gutter="18">
            <el-col :xs="24" :sm="8">
              <el-form-item label="是否附发票" label-width="118px">
                <el-radio-group v-model="form.has_invoice" :disabled="recognizeState === 'running'">
                  <el-radio-button :value="1">是</el-radio-button>
                  <el-radio-button :value="0">否</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="16">
              <el-form-item :label="form.has_invoice ? '报销金额(元)' : '报销金额(元)'" label-width="118px">
                <el-input-number v-model="form.amount" :min="0" :precision="2" :controls="false"
                                 placeholder="0.00" style="width: 220px"
                                 :disabled="form.has_invoice === 1 && recognizeState === 'done'" />
                <span class="amount-hint">
                  {{ form.has_invoice === 1
                    ? '默认由票据「价税合计」带出，如与票据不一致请修改票据字段'
                    : '未附发票时必填，且必须大于 0' }}
                </span>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 上传区：仅附发票时显示 -->
          <div v-if="form.has_invoice === 1" class="upload-block">
            <el-upload ref="uploadRef" drag :auto-upload="false" :show-file-list="false" :limit="1"
                       accept=".pdf,.jpg,.jpeg,.png,image/jpeg,image/png,application/pdf"
                       :on-change="onFileChange" :on-exceed="onExceed"
                       :disabled="recognizeState === 'running'">
              <el-icon class="up-icon"><UploadFilled /></el-icon>
              <div class="up-text">将票据拖到此处，或<em>点击选择文件</em></div>
              <div class="up-sub">支持 PDF / JPG / JPEG / PNG；图片不超过 8MB，PDF 不超过 20MB</div>
            </el-upload>

            <!-- 已选文件预览 -->
            <div v-if="fileInfo" class="file-preview">
              <img v-if="previewUrl && isImage" :src="previewUrl" alt="票据预览" class="thumb" />
              <div v-else class="thumb file-thumb">
                <el-icon><Document /></el-icon>
                <span>{{ isImage ? '图片' : 'PDF 文档' }}</span>
              </div>
              <div class="file-meta">
                <div class="fm-name" :title="fileInfo.name">{{ fileInfo.name }}</div>
                <div class="fm-size">{{ fileSizeText }} · {{ isImage ? '图片' : 'PDF' }}</div>
                <div class="fm-ops">
                  <el-button v-if="recognizeState !== 'running'" link type="primary"
                             :icon="MagicStick" @click="onRecognize">
                    {{ recognizeState === 'done' ? '重新识别' : 'AI 识别票据' }}
                  </el-button>
                  <el-button v-if="recognizeState !== 'running'" link type="danger" @click="clearFile">移除</el-button>
                </div>
              </div>
            </div>
            <div v-else class="file-empty">尚未选择票据文件</div>
          </div>

          <!-- 识别动作条 -->
          <div v-if="form.has_invoice === 1" class="recog-actions">
            <el-button type="primary" :icon="MagicStick" :loading="recognizeState === 'running'"
                       :disabled="!fileInfo || recognizeState === 'running'" @click="onRecognize">
              {{ recognizeState === 'running' ? '大模型识别中，请稍候……' : '下一步：AI 识别票据' }}
            </el-button>
            <el-button v-if="recognizeState === 'done'" :icon="View" @click="showInvoicePanel = !showInvoicePanel">
              {{ showInvoicePanel ? '收起识别结果' : '展开识别结果' }}
            </el-button>
            <span v-if="recognizeState === 'running'" class="recog-tip">
              视觉模型识别通常 20～60 秒，请勿关闭页面
            </span>
          </div>

          <!-- 识别中：进度提示 -->
          <div v-if="recognizeState === 'running'" class="recog-loading">
            <el-progress :percentage="100" :indeterminate="true" :duration="3" :show-text="false" :stroke-width="5" />
            <span>大模型识别中，请稍候……</span>
          </div>

          <!-- 识别失败：重试 / 跳过 -->
          <el-alert v-if="recognizeState === 'fail'" class="fail-alert" type="error" show-icon :closable="false"
                    title="票据识别失败" :description="recognizeError">
            <template #default>
              <div class="fail-body">
                <div class="fail-msg">{{ recognizeError }}</div>
                <div class="fail-ops">
                  <el-button size="small" type="primary" :icon="RefreshRight" @click="onRecognize">重试识别</el-button>
                  <el-button size="small" :icon="EditPen" @click="skipRecognize">跳过识别，手工填写票据信息</el-button>
                </div>
              </div>
            </template>
          </el-alert>
        </el-card>

        <!-- ============ 识别结果对照区（当前页展开） ============ -->
        <el-card v-if="showInvoicePanel" shadow="never" class="sec-card compare-card">
          <template #header>
            <div class="sec-head">
              <span class="sec-title">
                票据识别结果核对
                <el-tag v-if="recognizeSkipped" size="small" type="warning" effect="plain">手工填写</el-tag>
                <el-tag v-else size="small" type="success" effect="plain">AI 已识别</el-tag>
              </span>
              <span class="sec-hint">左侧为票据原件，右侧字段可直接修改；核对无误后点右上角「确认保存」</span>
            </div>
          </template>

          <!-- 识别告警 -->
          <el-alert v-if="recognizeWarnings.length" class="warn-alert" type="warning" show-icon :closable="false"
                    :title="`识别到 ${recognizeWarnings.length} 条需注意的信息`">
            <template #default>
              <ul class="warn-list">
                <li v-for="(w, i) in recognizeWarnings" :key="i">{{ w }}</li>
              </ul>
            </template>
          </el-alert>

          <div class="compare-body">
            <!-- 左：原件预览 -->
            <div class="cmp-left">
              <div class="cmp-head">票据原件</div>
              <div class="origin-box">
                <img v-if="previewUrl && isImage" :src="previewUrl" alt="票据原件" class="origin-img" />
                <iframe v-else-if="previewUrl && !isImage" :src="previewUrl" class="origin-pdf" title="票据 PDF 预览" />
                <div v-else class="origin-empty">
                  <el-icon><Document /></el-icon>
                  <span>无原件（手工填写票据信息）</span>
                </div>
              </div>
              <div class="origin-foot">
                <span>{{ fileInfo ? fileInfo.name : '未上传票据原件' }}</span>
                <el-button v-if="isImage && previewUrl" link type="primary" @click="openOrigin">查看大图</el-button>
              </div>

              <!-- 一致性提示（实时） -->
              <div class="consist-box">
                <div class="cmp-head">一致性提示</div>
                <div v-if="!consistencyList.length" class="consist-empty">暂无可比对项</div>
                <div v-for="c in consistencyList" :key="c.key" class="consist-item" :class="c.level">
                  <el-icon><CircleCheck v-if="c.level === 'ok'" /><WarningFilled v-else /></el-icon>
                  <span class="ci-text">{{ c.text }}</span>
                </div>
              </div>
            </div>

            <!-- 右：可编辑票据字段 -->
            <div class="cmp-right">
              <div class="cmp-head">
                票据字段
                <span class="cmp-sub">识别时间 {{ recognizeMeta.elapsed ? recognizeMeta.elapsed + ' 秒' : '—' }}
                  <template v-if="recognizeMeta.model"> · 模型 {{ recognizeMeta.model }}</template>
                </span>
              </div>
              <el-form :model="invoice" label-width="104px" label-position="right" size="default">
                <el-row :gutter="12">
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="票据类型">
                      <el-select v-model="invoice.document_type" filterable allow-create clearable style="width: 100%"
                                 placeholder="选择或输入票据类型">
                        <el-option v-for="t in DOC_TYPES" :key="t" :label="t" :value="t" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="是否为发票">
                      <el-radio-group v-model="invoice.is_invoice">
                        <el-radio-button :value="1">是</el-radio-button>
                        <el-radio-button :value="0">否</el-radio-button>
                      </el-radio-group>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="发票代码">
                      <el-input v-model="invoice.invoice_code" placeholder="发票代码" maxlength="32" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="发票号码">
                      <el-input v-model="invoice.invoice_number" placeholder="发票号码（唯一，重复将被拒绝）" maxlength="64" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="开票日期">
                      <el-date-picker v-model="invoice.issue_date" type="date" value-format="YYYY-MM-DD"
                                      placeholder="开票日期" style="width: 100%" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="价税合计">
                      <el-input-number v-model="invoice.total_amount" :min="0" :precision="2" :controls="false"
                                       style="width: 100%" placeholder="0.00" @change="onTotalAmountChange" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="购买方名称">
                      <el-input v-model="invoice.buyer_name" placeholder="购买方名称（须与本单位一致）" maxlength="128" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="销售方名称">
                      <el-input v-model="invoice.seller_name" placeholder="销售方名称" maxlength="128" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="不含税金额">
                      <el-input-number v-model="invoice.amount_without_tax" :min="0" :precision="2" :controls="false"
                                       style="width: 100%" placeholder="0.00" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="税率 / 税额">
                      <div class="tax-row">
                        <el-input v-model="invoice.tax_rate" placeholder="如 6%" maxlength="16" style="width: 84px" />
                        <el-input-number v-model="invoice.tax_amount" :min="0" :precision="2" :controls="false"
                                         style="flex: 1" placeholder="税额" />
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :span="24">
                    <el-form-item label="大写金额">
                      <el-input v-model="invoice.total_amount_cn" placeholder="票据大写金额（用于勾稽校验）" maxlength="128" />
                    </el-form-item>
                  </el-col>
                </el-row>

                <el-divider content-position="left" class="cmp-divider">差旅要素（差旅费票据填写）</el-divider>
                <el-row :gutter="12">
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="乘车人">
                      <el-input v-model="invoice.passenger_name" placeholder="乘车人 / 住宿人姓名" maxlength="64" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="消费城市">
                      <el-input v-model="invoice.consume_city" placeholder="消费城市（如 杭州）" maxlength="64" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="出发地 / 到达地">
                      <div class="tax-row">
                        <el-input v-model="invoice.travel_from" placeholder="出发地" maxlength="64" style="flex: 1" />
                        <el-input v-model="invoice.travel_to" placeholder="到达地" maxlength="64" style="flex: 1" />
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="乘车日期">
                      <el-date-picker v-model="invoice.travel_date" type="date" value-format="YYYY-MM-DD"
                                      placeholder="乘车日期" style="width: 100%" />
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="入住 / 离店">
                      <div class="tax-row">
                        <el-date-picker v-model="invoice.checkin_date" type="date" value-format="YYYY-MM-DD"
                                        placeholder="入住" style="flex: 1; width: 100%" />
                        <el-date-picker v-model="invoice.checkout_date" type="date" value-format="YYYY-MM-DD"
                                        placeholder="离店" style="flex: 1; width: 100%" />
                      </div>
                    </el-form-item>
                  </el-col>
                  <el-col :xs="24" :sm="12">
                    <el-form-item label="票据晚数">
                      <el-input-number v-model="invoice.nights" :min="0" :max="365" :precision="0"
                                       controls-position="right" style="width: 100%" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="24">
                    <el-form-item label="AI 建议类型">
                      <el-input v-model="invoice.suggested_expense_type"
                                placeholder="大模型识别出的费用类型，未手动选择时会自动填入上方「费用类型」" maxlength="64" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="24">
                    <el-form-item label="备注">
                      <el-input v-model="invoice.remark" type="textarea" :rows="2" maxlength="200" placeholder="票据备注" />
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form>
            </div>
          </div>
        </el-card>

        <!-- 底部动作（长页面便于就近保存） -->
        <div class="foot-actions">
          <el-button :icon="Back" @click="goBack">返回列表</el-button>
          <el-button type="primary" :icon="Check" :loading="saving" @click="onSave">确认保存</el-button>
        </div>
      </div>

      <!-- ================= 右：填写引导 / 缺失项提示 ================= -->
      <div class="edit-side">
        <el-card shadow="never" class="side-card">
          <template #header><span class="sec-title">填写检查</span></template>
          <div class="chk-summary">
            <div class="chk-num" :class="missingFields.length ? 'warn' : 'ok'">{{ missingFields.length }}</div>
            <div class="chk-label">{{ missingFields.length ? '项建议补充' : '建议项已齐全' }}</div>
          </div>
          <div v-if="missingFields.length" class="chk-list">
            <div v-for="(m, i) in missingFields" :key="i" class="chk-item">
              <el-icon><Warning /></el-icon><span>{{ m }}</span>
            </div>
            <div class="chk-tip">以上均为制度建议项，不影响保存；但缺失可能导致 AI 判读为「不合规」。</div>
          </div>
          <div v-else class="chk-ok">
            <el-icon><CircleCheck /></el-icon><span>必填与建议项均已填写</span>
          </div>
        </el-card>

        <el-card shadow="never" class="side-card">
          <template #header><span class="sec-title">填写须知</span></template>
          <ol class="notice-list">
            <li>报销日期取服务器当前日期，不可修改。</li>
            <li>费用发生日期建议与票据开票日期相差 3 天以内，跨年度报销须在情况说明中注明。</li>
            <li>差旅住宿费按城市等级执行标准，超标须填写特批人及情况说明。</li>
            <li>业务招待费须填写招待对象单位与陪同人数，周末 / 节假日招待须说明原因。</li>
            <li>无发票全额不得抵扣进项税，且须手工填写报销金额。</li>
            <li>保存后系统将把本单提交 AI 合规判读，判读结论决定能否制证。</li>
          </ol>
        </el-card>

        <el-card v-if="specialInfo === '差旅' && cityHint" shadow="never" class="side-card">
          <template #header><span class="sec-title">住宿标准</span></template>
          <div class="city-info">
            <div class="ci-city">{{ form.travel_city }}</div>
            <div class="ci-line">城市等级：<b>{{ cityHint.city_level }}</b></div>
            <div class="ci-line">住宿上限：<b>{{ cityHint.lodging_limit }} 元/晚</b></div>
            <div class="ci-line" v-if="form.nights">按 {{ form.nights }} 晚计，上限合计
              <b>{{ fmtMoney((cityHint.lodging_limit || 0) * (form.nights || 0)) }} 元</b>
            </div>
            <div class="ci-line" v-if="form.amount && form.nights">
              实际每晚：<b :class="{ over: nightlyAmount > (cityHint.lodging_limit || 0) }">
                {{ fmtMoney(nightlyAmount) }} 元</b>
            </div>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  EditPen, Calendar, Check, Back, UploadFilled, Document, MagicStick,
  RefreshRight, View, CircleCheck, WarningFilled, Warning, InfoFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reimburseApi } from '@/api/reimburse'
import { APPROVER_LEVELS, fmtMoney, dayDiff, normalizeCity, sameCity } from './constants'

const route = useRoute()
const router = useRouter()

// 编辑模式：/rmb/bill/:id/edit
const editId = computed(() => route.params.id || null)
const isEdit = computed(() => !!editId.value)

/** 票据类型：与后端 invoice_ai 的 document_type 枚举保持一致 */
const DOC_TYPES = [
  '增值税专用发票', '增值税普通发票', '电子发票（增值税专用发票）', '电子发票（普通发票）',
  '电子发票（铁路电子客票）', '航空运输电子客票行程单', '出租车发票', '定额发票', '收据', '其他'
]

// ---- 下拉与服务器日期 ----
const meta = reactive({
  today: '', expense_types: [], settlement_methods: [], departments: [], employees: [],
  city_levels: [], params: {}, current_employee: null, can_choose_employee: false,
  approvers: []
})

const formRef = ref()
const form = reactive({
  employee_id: null, expense_type_id: null, settlement_method_id: null,
  reason: '', occur_date: '', amount: null, has_invoice: 1,
  approver_name: '', approver_level: '',
  travel_city: '', travel_start: '', travel_end: '', nights: 0,
  guest_company: '', guest_count: 0,
  special_approver: '', explanation: ''
})

const rules = {
  employee_id: [{ required: true, message: '请选择报销人', trigger: 'change' }],
  expense_type_id: [{ required: true, message: '请选择费用类型', trigger: 'change' }],
  occur_date: [{ required: true, message: '请选择费用发生日期', trigger: 'change' }]
}

// ---- 票据文件与识别状态 ----
const uploadRef = ref()
const fileInfo = ref(null)          // { raw, name, size, mime }
const previewUrl = ref('')
const recognizeState = ref('idle')  // idle | running | done | fail
const recognizeError = ref('')
const recognizeWarnings = ref([])
const recognizeMeta = reactive({ model: '', elapsed: 0 })
const recognizeSkipped = ref(false) // 用户跳过识别的标记
const recognizeToken = ref('')
const showInvoicePanel = ref(false)

// ---- AI 生成报销事由 ----
const reasonLoading = ref(false)

const emptyInvoice = () => ({
  document_type: '', is_invoice: 1, invoice_code: '', invoice_number: '', issue_date: '',
  buyer_name: '', buyer_tax_id: '', seller_name: '', seller_tax_id: '',
  amount_without_tax: 0, tax_rate: '', tax_amount: 0, total_amount: 0, total_amount_cn: '',
  passenger_name: '', travel_from: '', travel_to: '', travel_date: '',
  checkin_date: '', checkout_date: '', nights: 0, consume_city: '',
  remark: '', suggested_expense_type: ''
})
const invoice = reactive(emptyInvoice())

// ---- 保存结果 ----
const saving = ref(false)
const savedInfo = ref(null)
/** 编辑模式下已存在的票据（后端已按 ID 关联，保存时无需回传） */
const existingInvoice = ref(null)

// ---- 派生：费用类型专项、报销人部门 ----
const specialInfo = computed(() => {
  const t = (meta.expense_types || []).find((x) => x.id === form.expense_type_id)
  return t?.special_info || '无'
})
/** AI 识别建议的费用类型：按名称与系统费用类型表对齐（忽略空格差异），匹配不到返回 null */
const suggestedType = computed(() => {
  const name = String(invoice.suggested_expense_type || '').replace(/[\s　]/g, '')
  if (!name) return null
  return (meta.expense_types || []).find(
    (t) => String(t.name || '').replace(/[\s　]/g, '') === name
  ) || null
})
const currentEmployeeName = computed(() => {
  if (meta.current_employee) return `${meta.current_employee.name}（本人）`
  return '未关联员工，请联系管理员'
})
const departmentName = computed(() => {
  if (meta.can_choose_employee) {
    const e = (meta.employees || []).find((x) => x.id === form.employee_id)
    return e?.department_name || ''
  }
  return meta.current_employee?.department_name || ''
})
const travelRange = ref([])
const nightsManual = ref(false)
const isImage = computed(() => !!fileInfo.value && String(fileInfo.value.mime).startsWith('image/'))
const fileSizeText = computed(() => {
  const kb = Math.max(1, Math.round((fileInfo.value?.size || 0) / 1024))
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`
})
const cityHint = computed(() => (meta.city_levels || []).find((c) => c.city_name === form.travel_city) || null)
const nightlyAmount = computed(() => (form.nights ? (Number(form.amount) || 0) / form.nights : 0))
const perCapitaText = computed(() => {
  const c = Number(form.guest_count) || 0
  if (!c) return '填写陪同人数后自动计算'
  return `${fmtMoney((Number(form.amount) || 0) / c)} 元 / 人（共 ${c} 人）`
})
const travelTip = computed(() => {
  if (!form.travel_city) return '建议填写出差地点，用于匹配城市等级与住宿标准'
  if (!cityHint.value) return `「${form.travel_city}」不在城市等级表中，将按「其他城市」标准判读`
  if (form.nights) {
    return `按 ${cityHint.value.city_level} 标准，住宿上限 ${cityHint.value.lodging_limit} 元/晚，共 ${form.nights} 晚`
  }
  return '出差起止日期变更后自动推算住宿晚数，可手工修正'
})

/**
 * 制度建议项（缺失仅提示，不阻断保存）。
 * 必填项（报销人 / 费用类型 / 发生日期）由 el-form 校验拦截，不在此列。
 */
const missingFields = computed(() => {
  const out = []
  if (!form.reason) out.push('缺报销事由')
  if (!form.settlement_method_id) out.push('缺结算方式')
  if (!form.approver_name) out.push('缺审批人姓名')
  if (!form.approver_level) out.push('缺审批层级')
  if (specialInfo.value === '差旅') {
    if (!form.travel_city) out.push('缺出差地点')
    if (!form.travel_start || !form.travel_end) out.push('缺出差起止日期')
    if (!form.nights) out.push('缺住宿晚数')
  }
  if (specialInfo.value === '招待') {
    if (!form.guest_company) out.push('缺招待对象单位')
    if (!form.guest_count) out.push('缺陪同人数')
  }
  if (!form.has_invoice && !(Number(form.amount) > 0)) out.push('无发票时须填写报销金额')
  return out
})

// ---- 一致性提示：报销单 ⇄ 票据 ----
const consistencyList = computed(() => {
  const list = []
  const amt = Number(form.amount) || 0
  const total = Number(invoice.total_amount) || 0
  // 1. 报销金额 vs 价税合计
  if (amt > 0 && total > 0) {
    const diff = Math.abs(amt - total)
    list.push(diff > 0.01
      ? { key: 'amt', level: 'warn', text: `报销金额 ${fmtMoney(amt)} 与票据价税合计 ${fmtMoney(total)} 不一致（差 ${fmtMoney(diff)} 元）` }
      : { key: 'amt', level: 'ok', text: `报销金额与票据价税合计一致（${fmtMoney(amt)} 元）` })
  } else if (amt > 0 && !total) {
    list.push({ key: 'amt', level: 'warn', text: `报销金额 ${fmtMoney(amt)} 元，票据价税合计为空，请补充票据金额` })
  }
  // 2. 发生日期 vs 开票日期
  const d = dayDiff(invoice.issue_date, form.occur_date)
  if (d !== null) {
    const abs = Math.abs(d)
    list.push(abs > 3
      ? { key: 'date', level: 'warn', text: `费用发生日期与开票日期相差 ${abs} 天（超过 3 天），跨期报销须在情况说明中注明` }
      : { key: 'date', level: 'ok', text: `费用发生日期与开票日期相差 ${abs} 天（≤3 天）` })
  }
  // 3. 乘车人 vs 报销人（与后端判读口径一致：忽略首尾空白，支持「王*五」脱敏写法）
  const empName = (meta.employees || []).find((e) => e.id === form.employee_id)?.name || meta.current_employee?.name || ''
  const passenger = String(invoice.passenger_name || '').trim()
  if (passenger && empName) {
    list.push(sameName(passenger, empName)
      ? { key: 'psg', level: 'ok', text: `乘车人 ${passenger} 与报销人一致` }
      : { key: 'psg', level: 'warn', text: `乘车人「${passenger}」与报销人「${empName}」不一致，请确认是否为代报销` })
  }
  // 4. 消费城市 vs 出差地点（sameCity：容忍「上海市」「上海虹桥」等写法差异）
  if (invoice.consume_city && form.travel_city) {
    const cities = (meta.city_levels || []).map((c) => c.city_name)
    list.push(sameCity(invoice.consume_city, form.travel_city, cities)
      ? { key: 'city', level: 'ok', text: `消费城市与出差地点一致（${form.travel_city}）` }
      : { key: 'city', level: 'warn', text: `票据消费城市「${invoice.consume_city}」与出差地点「${form.travel_city}」不一致` })
  }
  // 5. 票据晚数 vs 填报晚数
  if (specialInfo.value === '差旅' && Number(invoice.nights) > 0 && Number(form.nights) > 0) {
    list.push(Number(invoice.nights) === Number(form.nights)
      ? { key: 'nights', level: 'ok', text: `票据晚数与填报住宿晚数一致（${form.nights} 晚）` }
      : { key: 'nights', level: 'warn', text: `票据晚数 ${invoice.nights} 晚与填报住宿晚数 ${form.nights} 晚不一致` })
  }
  // 6. AI 建议费用类型 vs 所选类型（按归一后的名称比对，容忍空格差异）
  const selType = (meta.expense_types || []).find((t) => t.id === form.expense_type_id)?.name || ''
  if (invoice.suggested_expense_type && selType) {
    const sameType = !!suggestedType.value && suggestedType.value.id === form.expense_type_id
    list.push(sameType
      ? { key: 'type', level: 'ok', text: `AI 建议费用类型与所选类型一致（${selType}）` }
      : { key: 'type', level: 'warn', text: `AI 建议费用类型为「${invoice.suggested_expense_type}」，与所选「${selType}」不一致` })
  }
  return list
})

// ---- 数据加载 ----
async function loadMeta() {
  const res = await reimburseApi.meta()
  Object.assign(meta, {
    today: res?.today || '',
    expense_types: res?.expense_types || [],
    settlement_methods: res?.settlement_methods || [],
    departments: res?.departments || [],
    employees: res?.employees || [],
    city_levels: res?.city_levels || [],
    params: res?.params || {},
    current_employee: res?.current_employee || null,
    can_choose_employee: !!res?.can_choose_employee,
    approvers: res?.approvers || []
  })
  // 普通报销人：固定本人
  if (!meta.can_choose_employee && meta.current_employee) {
    form.employee_id = meta.current_employee.id
  }
}

/** 编辑模式回填：优先用后端给的 id，缺失时按名称在 meta 中匹配（契约仅约定返回 *_name） */
function matchIdByName(list, name) {
  if (!name) return null
  return (list || []).find((x) => x.name === name)?.id || null
}

async function loadDetail(id) {
  const d = await reimburseApi.detail(id)
  Object.assign(form, {
    employee_id: d.employee_id ?? matchIdByName(meta.employees, d.employee_name) ?? form.employee_id,
    expense_type_id: d.expense_type_id ?? matchIdByName(meta.expense_types, d.expense_type_name),
    settlement_method_id: d.settlement_method_id ?? matchIdByName(meta.settlement_methods, d.settlement_method_name),
    reason: d.reason || '',
    occur_date: d.occur_date || '',
    amount: d.amount === null || d.amount === undefined ? null : Number(d.amount),
    has_invoice: d.has_invoice === 0 || d.has_invoice === false ? 0 : 1,
    approver_name: d.approver_name || '',
    approver_level: d.approver_level || '',
    travel_city: d.travel_city || '',
    travel_start: d.travel_start || '',
    travel_end: d.travel_end || '',
    nights: Number(d.nights || 0),
    guest_company: d.guest_company || '',
    guest_count: Number(d.guest_count || 0),
    special_approver: d.special_approver || '',
    explanation: d.explanation || ''
  })
  travelRange.value = d.travel_start && d.travel_end ? [d.travel_start, d.travel_end] : []
  if (d.nights) nightsManual.value = true
  savedInfo.value = { id: d.id, bill_no: d.bill_no }
  // 已存在的票据：回填字段（原件需重新上传才能再次识别）
  if (d.invoice) {
    existingInvoice.value = d.invoice
    Object.assign(invoice, emptyInvoice(), d.invoice)
    // items 在后端是 JSON 字符串，前端不再编辑，原样回传
    recognizeState.value = 'done'
    recognizeSkipped.value = true
    showInvoicePanel.value = true
    recognizeToken.value = d.invoice.token || ''
  }
}

// ---- 交互 ----
function goBack() { router.push('/reimburse/list') }
function goCompliance() {
  if (!savedInfo.value) return
  router.push(`/rmb/compliance/${savedInfo.value.id}?auto=1`)
}
function openOrigin() {
  if (previewUrl.value) window.open(previewUrl.value, '_blank')
}

function onEmployeeChange(id) {
  const e = (meta.employees || []).find((x) => x.id === id)
  if (e && !meta.can_choose_employee) form.employee_id = id
}

/** 选择审批人后自动带出其审批层级（仍可手动修改） */
function onApproverChange(name) {
  const hit = (meta.approvers || []).find((a) => a.name === name)
  if (hit?.level) form.approver_level = hit.level
}

function onExpenseTypeChange() {
  // 切换费用类型后清空不适用的专项字段，避免脏数据提交
  if (specialInfo.value !== '差旅') {
    form.travel_city = ''; form.travel_start = ''; form.travel_end = ''; form.nights = 0
    travelRange.value = []
  }
  if (specialInfo.value !== '招待') {
    form.guest_company = ''; form.guest_count = 0
  }
}

/**
 * 采用 AI 识别出的费用类型。
 * notify=true 用于用户手动点「采用」，给一次明确反馈；
 * 默认为 false，供识别完成后的自动填充静默调用。
 */
function applySuggestedType(notify = false) {
  const t = suggestedType.value
  if (!t || form.expense_type_id === t.id) return false
  form.expense_type_id = t.id
  onExpenseTypeChange()
  formRef.value?.validateField('expense_type_id').catch(() => {})
  if (notify) ElMessage.success(`已采用 AI 识别的费用类型：${t.name}`)
  return true
}

/** YYYY-MM-DD 加 n 天（用于「入住日期 + 住宿晚数 = 离店日期」） */
function addDays(dateStr, days) {
  if (!dateStr) return ''
  const d = new Date(String(dateStr).replace(/-/g, '/'))
  if (Number.isNaN(d.getTime())) return ''
  d.setDate(d.getDate() + (Number(days) || 0))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** 姓名一致性：忽略首尾空白，支持「王*五」这类脱敏写法（与后端 fact_service._name_matched 口径一致） */
function sameName(a, b) {
  const x = String(a || '').trim()
  const y = String(b || '').trim()
  if (!x || !y) return false
  if (x === y) return true
  if (/[*xX]/.test(x)) {
    const stripped = x.replace(/[*xX]/g, '')
    return !!stripped && stripped[0] === y[0] && stripped[stripped.length - 1] === y[y.length - 1]
  }
  return false
}

/** 出差地点归一化：把「上海虹桥」「上海市」这类站名/行政区名归到城市等级表里的城市名 */
function normalizeTravelCity(raw) {
  return normalizeCity(raw, (meta.city_levels || []).map((c) => c.city_name))
}

/**
 * 识别结果 → 差旅专项信息（出差地点 / 出差起止日期 / 住宿晚数）。
 * 只填补空字段，不覆盖用户已填内容；返回本次自动填充的字段名，供提示使用。
 * - 出差地点：住宿发票取消费城市，交通票据取到达地（站名归一到城市名）；
 * - 出差起止日期：住宿票取入住 / 离店（离店缺失时按入住 + 晚数推算），交通票取乘车日期；
 * - 住宿晚数：票据晚数优先，其次由出差起止日期推算。
 */
function applyInvoiceTravelInfo() {
  if (specialInfo.value !== '差旅') return []
  const filled = []
  // 1) 出差地点
  const city = normalizeTravelCity(invoice.consume_city || invoice.travel_to)
  if (city && !form.travel_city) {
    form.travel_city = city
    filled.push('出差地点')
  }
  // 2) 出差起止日期
  let start = (invoice.checkin_date || '').trim()
  let end = (invoice.checkout_date || '').trim()
  if (!start && invoice.travel_date) {
    start = invoice.travel_date
    end = invoice.travel_date
  }
  if (!end && start && Number(invoice.nights) > 0) end = addDays(start, Number(invoice.nights))
  if (start && !form.travel_start) {
    form.travel_start = start
    filled.push('出差开始日期')
  }
  if (end && !form.travel_end) {
    form.travel_end = end
    filled.push('出差结束日期')
  }
  // 日期范围组件与 form 单向同步：程序赋值不会触发 change，这里手动回填
  if (form.travel_start && form.travel_end) travelRange.value = [form.travel_start, form.travel_end]
  // 3) 住宿晚数
  if (!Number(form.nights)) {
    let nights = Number(invoice.nights) || 0
    if (!nights && form.travel_start && form.travel_end) {
      const diff = dayDiff(form.travel_start, form.travel_end)
      nights = diff && diff > 0 ? diff : 0
    }
    if (nights > 0) {
      form.nights = nights
      filled.push('住宿晚数')
    }
  }
  return filled
}

/** 出差起止日期 → 自动推算住宿晚数（用户手工改过后不再覆盖） */
function onTravelRangeChange(val) {
  form.travel_start = val?.[0] || ''
  form.travel_end = val?.[1] || ''
  if (nightsManual.value) return
  const d = dayDiff(form.travel_start, form.travel_end)
  form.nights = d && d > 0 ? d : 0
}

/** 城市等级建议：按城市名过滤，最多 8 条 */
function queryCity(q, cb) {
  const kw = (q || '').trim()
  const all = (meta.city_levels || []).map((c) => ({
    value: c.city_name, city_level: c.city_level, lodging_limit: c.lodging_limit
  }))
  cb(kw ? all.filter((c) => c.value.includes(kw)).slice(0, 8) : all.slice(0, 8))
}

function revokePreview() {
  if (previewUrl.value && previewUrl.value.startsWith('blob:')) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

function onFileChange(uploadFile) {
  const raw = uploadFile?.raw
  uploadRef.value?.clearFiles()
  if (!raw) return
  // 类型先判断，再按类型区分大小上限（与后端一致：图片 8MB、PDF 20MB）
  const okType = /^(image\/(jpeg|jpg|png)|application\/pdf)$/.test(raw.type)
  if (!okType) {
    ElMessage.warning('仅支持 PDF / JPG / JPEG / PNG 格式的票据')
    return
  }
  const isPdfFile = raw.type === 'application/pdf' || /\.pdf$/i.test(raw.name || '')
  const maxMb = isPdfFile ? 20 : 8
  if (raw.size > maxMb * 1024 * 1024) {
    ElMessage.warning(`票据文件不能超过 ${maxMb}MB`)
    return
  }
  revokePreview()
  fileInfo.value = { raw, name: raw.name, size: raw.size, mime: raw.type }
  previewUrl.value = URL.createObjectURL(raw)
  // 换文件后旧识别结果作废
  resetRecognize()
}

function onExceed() {
  ElMessage.warning('一次只能上传一张票据，请先移除已选文件')
}

function clearFile() {
  revokePreview()
  fileInfo.value = null
  uploadRef.value?.clearFiles()
  resetRecognize()
}

/** 重置识别状态（换文件 / 移除文件时调用） */
function resetRecognize() {
  recognizeState.value = 'idle'
  recognizeError.value = ''
  recognizeWarnings.value = []
  recognizeMeta.model = ''
  recognizeMeta.elapsed = 0
  recognizeToken.value = ''
  recognizeSkipped.value = false
  showInvoicePanel.value = false
}

async function onRecognize() {
  if (!fileInfo.value) return ElMessage.warning('请先选择票据文件')
  recognizeState.value = 'running'
  recognizeError.value = ''
  recognizeWarnings.value = []
  try {
    const fd = new FormData()
    fd.append('file', fileInfo.value.raw)
    // 表单字段供大模型结合上下文识别（均为可选）。
    // 空值不 append：后端按 Form 解析时，空串会让 int/float 字段校验失败
    // （"Input should be a valid integer"），导致整次识别被打回。
    const appendIfValue = (key, value) => {
      if (value === null || value === undefined) return
      if (typeof value === 'string' && !value.trim()) return
      fd.append(key, String(value))
    }
    appendIfValue('expense_type_id', form.expense_type_id)
    appendIfValue('employee_id', form.employee_id)
    appendIfValue('occur_date', form.occur_date)
    appendIfValue('amount', form.amount)
    const res = await reimburseApi.recognize(fd)
    recognizeToken.value = res?.token || ''
    recognizeWarnings.value = res?.warnings || []
    Object.assign(invoice, emptyInvoice(), res?.invoice || {})
    recognizeMeta.model = res?.model || res?.invoice?.llm_model || ''
    recognizeMeta.elapsed = res?.elapsed || res?.invoice?.elapsed || 0
    recognizeState.value = 'done'
    recognizeSkipped.value = false
    showInvoicePanel.value = true
    // 金额未填时用价税合计带出
    if (!Number(form.amount) && Number(invoice.total_amount)) {
      form.amount = Number(invoice.total_amount)
    }
    // 费用发生日期未填时用开票日期带出
    if (!form.occur_date && invoice.issue_date) form.occur_date = invoice.issue_date
    // 费用类型未选时自动采用 AI 识别的建议；已选则保留用户选择，差异由一致性提示给出
    const autoPicked = !form.expense_type_id && applySuggestedType()
    // 差旅类：把票据里的消费城市 / 入住离店 / 晚数回填到「差旅专项信息」
    const travelFilled = applyInvoiceTravelInfo()
    const filledParts = []
    if (autoPicked) filledParts.push(`费用类型「${suggestedType.value.name}」`)
    if (travelFilled.length) filledParts.push(`差旅专项（${travelFilled.join('、')}）`)
    ElMessage.success(filledParts.length
      ? `票据识别完成，已自动填充：${filledParts.join('；')}，请核对识别结果`
      : '票据识别完成，请核对识别结果')
  } catch (e) {
    recognizeState.value = 'fail'
    recognizeError.value = e?.message || '票据识别失败，请重试或手工填写票据信息'
  }
}

/** 跳过识别，手工填写票据字段 */
function skipRecognize() {
  recognizeState.value = 'idle'
  recognizeError.value = ''
  recognizeSkipped.value = true
  Object.assign(invoice, emptyInvoice())
  recognizeToken.value = ''
  showInvoicePanel.value = true
  ElMessage.info('已跳过识别，请手工填写票据字段')
}

/** 价税合计变动时同步报销金额（仅在金额为空或此前与旧值一致时跟随） */
let lastTotal = 0
function onTotalAmountChange(v) {
  const nv = Number(v) || 0
  const cur = Number(form.amount) || 0
  const old = Number(lastTotal) || 0
  if (!cur || Math.abs(cur - old) < 0.01) form.amount = nv
  lastTotal = nv
}

/** AI 生成报销事由：把已填写的报销信息与票据识别结果交给后端文本模型生成 */
async function onSuggestReason() {
  if (reasonLoading.value) return
  const hasInvoice = !!(invoice.total_amount || invoice.document_type || invoice.seller_name)
  if (!form.expense_type_id && !hasInvoice) {
    ElMessage.warning('请先选择费用类型或上传票据，AI 生成的事由会更完整')
    return
  }
  if (!form.occur_date && !hasInvoice) {
    ElMessage.warning('建议先填写费用发生日期或上传票据，AI 生成的事由会更完整')
    return
  }
  reasonLoading.value = true
  try {
    const res = await reimburseApi.suggestReason({
      expense_type_id: form.expense_type_id,
      occur_date: form.occur_date,
      amount: Number(form.amount) || null,
      has_invoice: form.has_invoice ? 1 : 0,
      travel_city: form.travel_city,
      travel_start: form.travel_start,
      travel_end: form.travel_end,
      nights: Number(form.nights) || 0,
      guest_company: form.guest_company,
      guest_count: Number(form.guest_count) || 0,
      invoice: hasInvoice ? { ...invoice } : null
    })
    form.reason = res?.reason || ''
    ElMessage.success('已生成报销事由，可自行修改')
  } catch (e) {
    ElMessage.error(e?.message || 'AI 生成报销事由失败，请手工填写')
  } finally {
    reasonLoading.value = false
  }
}

// ---- 保存 ----
function buildPayload() {
  const payload = {
    employee_id: form.employee_id,
    department_id: (meta.employees || []).find((e) => e.id === form.employee_id)?.department_id
      ?? meta.current_employee?.department_id ?? null,
    expense_type_id: form.expense_type_id,
    settlement_method_id: form.settlement_method_id,
    reason: form.reason,
    occur_date: form.occur_date,
    amount: Number(form.amount) || 0,
    has_invoice: form.has_invoice ? 1 : 0,
    approver_name: form.approver_name,
    approver_level: form.approver_level,
    travel_city: form.travel_city,
    travel_start: form.travel_start,
    travel_end: form.travel_end,
    nights: Number(form.nights) || 0,
    guest_company: form.guest_company,
    guest_count: Number(form.guest_count) || 0,
    special_approver: form.special_approver,
    explanation: form.explanation,
    invoice_token: recognizeToken.value,
    token: recognizeToken.value
  }
  // 附发票：仅在「本次上传并已识别 / 手工填写」时提交票据对象；
  // 编辑模式下票据已存在且后端按 ID 关联，不重复回传（避免覆盖原有 file_hash 等字段）。
  const invoiceChanged = !!fileInfo.value || !existingInvoice.value
  if (form.has_invoice && invoiceChanged && (recognizeState.value === 'done' || recognizeSkipped.value)) {
    payload.invoice = { ...invoice }
  }
  return payload
}

/** 保存前校验：只强制 报销人 / 费用类型 / 发生日期 + 票据齐全性 */
async function validateBeforeSave() {
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) {
    ElMessage.warning('请先补全必填项（报销人 / 费用类型 / 费用发生日期）')
    return false
  }
  if (form.has_invoice === 1) {
    // 编辑模式下票据已存在，不要求重新上传
    const hasExisting = !!existingInvoice.value && !fileInfo.value
    if (!fileInfo.value && !hasExisting) {
      ElMessage.warning('已选择「附发票」，请上传票据文件')
      return false
    }
    if (!hasExisting && recognizeState.value === 'idle' && !recognizeSkipped.value) {
      ElMessage.warning('请先点击「下一步：AI 识别票据」，或跳过识别手工填写票据信息')
      return false
    }
    if (recognizeState.value === 'running') {
      ElMessage.warning('票据正在识别中，请等待识别完成后再保存')
      return false
    }
  } else {
    if (!(Number(form.amount) > 0)) {
      ElMessage.warning('未附发票时，请填写大于 0 的报销金额')
      return false
    }
  }
  if (!(Number(form.amount) > 0)) {
    ElMessage.warning('请填写报销金额')
    return false
  }
  if (form.special_approver && !form.explanation) {
    try {
      await ElMessageBox.confirm('已填写特批人但未填写情况说明，确认继续保存？', '提示', { type: 'warning' })
    } catch { return false }
  }
  return true
}

async function onSave() {
  if (!(await validateBeforeSave())) return
  saving.value = true
  try {
    const payload = buildPayload()
    const res = savedInfo.value?.id
      ? await reimburseApi.update(savedInfo.value.id, payload)
      : await reimburseApi.save(payload)
    savedInfo.value = { id: res?.id ?? savedInfo.value?.id, bill_no: res?.bill_no || savedInfo.value?.bill_no }
    ElMessage.success(`保存成功，报销单号 ${savedInfo.value.bill_no || ''}`)
    // 首次保存后把地址换成编辑地址，避免刷新后回到「新建」
    if (res?.id) router.replace(`/rmb/bill/${res.id}/edit`)
    if (!isEdit.value) ElMessage.info('可点击右上角「提交 AI 合规判读」继续')
  } finally {
    saving.value = false
  }
}

// 差旅起止日期 synced：从 travelRange 单向同步到 form（已由 onTravelRangeChange 处理）
watch(() => form.has_invoice, (v) => {
  if (!v) {
    revokePreview()
    fileInfo.value = null
    resetRecognize()
  }
})

onMounted(async () => {
  await loadMeta()
  if (editId.value) {
    await loadDetail(editId.value)
  }
  lastTotal = Number(invoice.total_amount) || 0
})

onBeforeUnmount(revokePreview)
</script>

<style scoped>
.rmb-edit { gap: 12px; }
.edit-body { display: grid; grid-template-columns: minmax(0, 1fr) 292px; gap: 12px; align-items: start; }
.edit-main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.edit-side { display: flex; flex-direction: column; gap: 12px; position: sticky; top: 0; }

.sec-card :deep(.el-card__body) { padding: 14px 16px 4px; }
.sec-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.sec-title { font-weight: 700; color: var(--text-1); font-size: 14px; }
.sec-hint { font-size: 12px; color: var(--text-3); line-height: 1.5; }
.req { color: #f56c6c; font-style: normal; font-weight: 700; }
.city-limit { float: right; font-size: 12px; color: var(--text-3); margin-left: 12px; }
.amount-hint { margin-left: 10px; font-size: 12px; color: var(--text-3); }
.inline-tip {
  display: flex; align-items: center; gap: 6px; margin: -4px 0 12px 118px;
  font-size: 12px; color: #b88230; background: #fdf6ec; border-radius: 6px; padding: 5px 10px;
}
.tax-row { display: flex; gap: 8px; width: 100%; }
/* 费用类型的 AI 识别建议行（自动填充 / 一键采用） */
.ai-type-hint {
  display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
  width: 100%; margin-top: 2px; font-size: 12px; line-height: 18px; color: var(--text-2);
}
.ai-type-hint .el-icon { color: #e6a23c; }
.ai-type-hint b { color: #b88230; font-weight: 600; }
.ai-type-hint.warn { color: #b88230; }
.ai-type-apply { padding: 0; height: auto; font-size: 12px; }
.ai-type-done { color: #529b2e; }
/* 报销事由：文本框 + AI 生成按钮 */
.reason-field { width: 100%; }
.reason-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.reason-tip { font-size: 12px; color: var(--text-3); }

/* 上传区 */
.upload-block { margin-bottom: 12px; }
.upload-block :deep(.el-upload), .upload-block :deep(.el-upload-dragger) { width: 100%; }
.upload-block :deep(.el-upload-dragger) { padding: 18px 14px; }
.up-icon { font-size: 38px; color: var(--brand); }
.up-text { margin-top: 6px; font-size: 14px; color: var(--text-1); }
.up-text em { font-style: normal; font-weight: 600; color: var(--brand); }
.up-sub { margin-top: 4px; font-size: 12px; color: var(--text-3); }
.file-preview {
  display: flex; gap: 14px; align-items: flex-start; margin-top: 12px;
  padding: 10px 12px; border: 1px dashed var(--border); border-radius: 8px; background: #fafbfc;
}
.thumb { width: 132px; height: 96px; flex: 0 0 132px; object-fit: contain; border-radius: 6px; background: #fff; border: 1px solid var(--border); }
.file-thumb { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: var(--text-3); font-size: 12px; }
.file-thumb .el-icon { font-size: 26px; }
.file-meta { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.fm-name { font-size: 13px; font-weight: 600; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fm-size { font-size: 12px; color: var(--text-3); }
.fm-ops { display: flex; gap: 10px; margin-top: 2px; }
.file-empty { margin-top: 10px; font-size: 12px; color: var(--text-3); }

.recog-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.recog-tip { font-size: 12px; color: var(--text-3); }
.recog-loading { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 12px; color: var(--brand-dark); }
.recog-loading :deep(.el-progress) { flex: 1; }
.fail-alert { margin-bottom: 12px; }
.fail-body { display: flex; flex-direction: column; gap: 8px; }
.fail-msg { font-size: 13px; color: #c45656; }
.fail-ops { display: flex; gap: 8px; }
.warn-alert { margin-bottom: 12px; }
.warn-list { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; }

/* 识别结果对照区 */
.compare-card :deep(.el-card__body) { padding: 14px 16px; }
.compare-body { display: grid; grid-template-columns: minmax(0, 0.86fr) minmax(0, 1.14fr); gap: 14px; }
.cmp-left, .cmp-right { min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.cmp-right { border-left: 1px solid var(--border); padding-left: 14px; }
.cmp-head { font-size: 13px; font-weight: 600; color: var(--text-1); display: flex; align-items: baseline; gap: 8px; }
.cmp-sub { font-size: 12px; font-weight: 400; color: var(--text-3); }
.origin-box {
  border: 1px solid var(--border); border-radius: 8px; background: #fafbfc; overflow: hidden;
  height: 380px; display: flex; align-items: center; justify-content: center;
}
.origin-img { max-width: 100%; max-height: 100%; object-fit: contain; }
.origin-pdf { width: 100%; height: 100%; border: 0; }
.origin-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--text-3); font-size: 13px; }
.origin-empty .el-icon { font-size: 30px; }
.origin-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--text-3); }
.consist-box { border-top: 1px dashed var(--border); padding-top: 10px; }
.consist-empty { margin-top: 8px; font-size: 12px; color: var(--text-3); }
.consist-item {
  display: flex; align-items: flex-start; gap: 6px; margin-top: 7px; padding: 6px 9px;
  border-radius: 6px; font-size: 12px; line-height: 1.55;
}
.consist-item .el-icon { flex: 0 0 auto; margin-top: 2px; font-size: 14px; }
.consist-item.ok { background: #f0f9eb; color: #529b2e; }
.consist-item.warn { background: #fdf6ec; color: #b88230; }
.ci-text { word-break: break-all; }
.cmp-divider { margin: 6px 0 12px; font-size: 13px; }

/* 底部动作 */
.foot-actions { display: flex; justify-content: flex-end; gap: 10px; padding: 4px 0 8px; }

/* 右栏 */
.side-card :deep(.el-card__body) { padding: 14px 16px; }
.chk-summary { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.chk-num { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.chk-num.warn { color: #e6a23c; }
.chk-num.ok { color: #67c23a; }
.chk-label { font-size: 12px; color: var(--text-2); }
.chk-list { display: flex; flex-direction: column; gap: 6px; }
.chk-item { display: flex; align-items: flex-start; gap: 6px; font-size: 12px; color: #b88230; line-height: 1.5; }
.chk-item .el-icon { flex: 0 0 auto; margin-top: 2px; }
.chk-tip { margin-top: 8px; font-size: 12px; color: var(--text-3); line-height: 1.6; }
.chk-ok { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #529b2e; }
.notice-list { margin: 0; padding-left: 18px; font-size: 12px; line-height: 1.85; color: var(--text-2); }
.city-info { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--text-2); }
.ci-city { font-size: 15px; font-weight: 700; color: var(--text-1); }
.ci-line b { color: var(--text-1); }
.ci-line .over { color: #f56c6c; }

/* 窄屏：右栏下沉，两栏对照改为上下 */
@media (max-width: 1200px) {
  .edit-body { grid-template-columns: minmax(0, 1fr); }
  .edit-side { position: static; order: 2; }
}
@media (max-width: 992px) {
  .compare-body { grid-template-columns: minmax(0, 1fr); }
  .cmp-right { border-left: 0; padding-left: 0; border-top: 1px solid var(--border); padding-top: 12px; }
  .origin-box { height: 260px; }
  .inline-tip { margin-left: 0; }
}
</style>
