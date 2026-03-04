<template>
  <div style="height: 100vh; display: flex; flex-direction: column; background: #fff">
    <!-- 顶部三步引导 -->
    <div style="padding: 16px 40px; border-bottom: 1px solid #e4e7ed; background: #fff">
      <el-steps :active="wizardStep" finish-status="success" align-center>
        <el-step title="项目信息填报" />
        <el-step title="报告辅助生成" />
        <el-step title="报告预览导出" />
      </el-steps>
    </div>

    <!-- 主内容区 -->
    <div style="flex: 1; overflow-y: auto; padding: 24px 40px">

      <!-- ========== Step 1: 项目信息填报 ========== -->
      <div v-if="wizardStep === 0">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
          <h3 style="margin: 0">项目基本信息</h3>
          <div>
            <el-button @click="loadServerFacts" :loading="loadingFacts">
              加载已有配置
            </el-button>
            <el-upload :auto-upload="false" :show-file-list="false" accept=".json" :on-change="importJSON" style="display:inline-block; margin-left: 8px">
              <el-button>导入 JSON</el-button>
            </el-upload>
          </div>
        </div>

        <!-- ========== 文档上传区 (VL 智能识别) ========== -->
        <div style="background: #f0f7ff; border: 1px dashed #409eff; border-radius: 8px; padding: 20px; margin-bottom: 24px">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
            <div>
              <span style="font-size: 15px; font-weight: 600; color: #303133">
                <el-icon style="vertical-align: middle; margin-right: 4px"><Upload /></el-icon>
                智能文档识别
              </span>
              <span style="color: #909399; font-size: 12px; margin-left: 8px">
                上传项目文档，AI 自动提取信息填入表单
              </span>
            </div>
            <div>
              <el-button size="small" @click="loadSample" :loading="loadingSample">
                加载样本数据
              </el-button>
              <el-button size="small" type="danger" link @click="clearFiles" v-if="uploadedFiles.length > 0">
                清空文件
              </el-button>
            </div>
          </div>

          <!-- 上传区域 -->
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :show-file-list="false"
            multiple
            accept=".jpg,.jpeg,.png,.bmp,.pdf,.doc,.docx,.dwg,.dxf,.shp,.shx,.dbf,.prj,.geojson,.gpkg"
            :on-change="onFileChange"
            drag
            style="width: 100%"
          >
            <div style="padding: 20px 0">
              <el-icon style="font-size: 32px; color: #409eff"><Upload /></el-icon>
              <div style="color: #606266; margin-top: 8px">将项目文档拖拽到此处，或 <em style="color: #409eff">点击上传</em></div>
              <div style="color: #909399; font-size: 12px; margin-top: 4px">
                支持: 立项文件、施工许可证、图纸、土方合同、岩土报告、用地文件 (JPG/PNG/PDF/DOC/DWG/DXF/SHP)
              </div>
            </div>
          </el-upload>

          <!-- 已上传文件列表 -->
          <div v-if="uploadedFiles.length > 0" style="margin-top: 12px">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px">
              <span style="font-size: 13px; color: #606266">
                已上传 {{ uploadedFiles.length }} 个文件
                <span v-if="Object.keys(fileCategories).length" style="color: #909399">
                  ({{ Object.keys(fileCategories).map(k => k + ' ' + fileCategories[k].length + '个').join('、') }})
                </span>
              </span>
            </div>

            <!-- 分类显示 -->
            <div style="display: flex; flex-wrap: wrap; gap: 6px">
              <el-tag
                v-for="f in uploadedFiles" :key="f.name"
                :type="getFileTagType(f.name)"
                size="small"
                closable
                @close="removeFile(f.name)"
              >
                {{ f.name }}
              </el-tag>
            </div>

            <!-- VL 操作按钮 -->
            <div style="margin-top: 16px; display: flex; flex-wrap: wrap; gap: 12px">
              <el-button type="primary" @click="runExtract" :loading="extracting">
                <el-icon style="margin-right: 4px"><MagicStick /></el-icon>
                AI 提取项目信息
              </el-button>
              <el-button @click="runSiteDesc" :loading="generatingSiteDesc">
                <el-icon style="margin-right: 4px"><Picture /></el-icon>
                AI 生成现场描述
              </el-button>
              <el-button
                v-if="hasCadFiles"
                type="warning"
                @click="runCadConvert"
                :loading="convertingCad"
              >
                CAD 转 PNG
              </el-button>
              <el-button
                v-if="hasGisFiles"
                type="success"
                @click="runGisExtract"
                :loading="extractingGis"
              >
                GIS 导入分区
              </el-button>
              <el-button
                v-if="hasGisFiles && form.zones.length > 0 && form.zones[0].name"
                @click="runGisValidate"
                :loading="validatingGis"
              >
                GIS 面积校验
              </el-button>
              <el-tag v-if="vlStatus" :type="vlStatus === 'ok' ? 'success' : 'danger'" size="small" style="line-height: 32px">
                VL模型: {{ vlStatus === 'ok' ? '已连接' : '未连接' }}
              </el-tag>
            </div>

            <!-- GIS 校验结果 -->
            <div v-if="gisValidation" style="margin-top: 12px; padding: 12px; border-radius: 6px"
              :style="{ background: gisValidation.valid ? '#f0f9eb' : '#fef0f0', border: '1px solid ' + (gisValidation.valid ? '#e1f3d8' : '#fde2e2') }">
              <div style="font-weight: 600; margin-bottom: 6px">
                <span :style="{ color: gisValidation.valid ? '#67c23a' : '#f56c6c' }">
                  {{ gisValidation.valid ? '✓ 校验通过' : '✗ 校验不通过' }}
                </span>
                <span style="color: #909399; font-size: 12px; margin-left: 8px">
                  GIS总面积: {{ gisValidation.total_area_gis_hm2?.toFixed(4) }} hm²
                  | facts总面积: {{ gisValidation.total_area_facts_hm2?.toFixed(4) }} hm²
                  | 偏差: {{ gisValidation.total_diff_pct }}%
                </span>
              </div>
              <div v-for="msg in gisValidation.messages" :key="msg" style="font-size: 12px; color: #606266; line-height: 1.6">
                {{ msg }}
              </div>
            </div>
          </div>
        </div>

        <el-form :model="form" label-width="160px" label-position="right" size="default">

          <!-- 一、基本信息 -->
          <el-divider content-position="left">一、基本信息</el-divider>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-form-item label="项目名称" required>
                <el-input v-model="form.project_name" placeholder="如: 金石博雅园项目" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="建设单位" required>
                <el-input v-model="form.investor" placeholder="如: XX房地产开发有限公司" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="8">
              <el-form-item label="项目性质">
                <el-select v-model="form.project_nature" style="width: 100%">
                  <el-option label="新建" value="新建" />
                  <el-option label="改建" value="改建" />
                  <el-option label="扩建" value="扩建" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="项目类型">
                <el-select v-model="form.project_type" style="width: 100%" filterable allow-create>
                  <el-option label="房地产" value="房地产" />
                  <el-option label="市政道路" value="市政道路" />
                  <el-option label="工业厂房" value="工业厂房" />
                  <el-option label="学校" value="学校" />
                  <el-option label="医院" value="医院" />
                  <el-option label="水利工程" value="水利工程" />
                  <el-option label="交通工程" value="交通工程" />
                  <el-option label="能源工程" value="能源工程" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="审批级别">
                <el-select v-model="form.approval_level" style="width: 100%">
                  <el-option label="市级" value="市级" />
                  <el-option label="省级" value="省级" />
                  <el-option label="国家级" value="国家级" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 二、项目位置 -->
          <el-divider content-position="left">二、项目位置</el-divider>
          <el-row :gutter="24">
            <el-col :span="8">
              <el-form-item label="省份">
                <el-input v-model="form.location.province" placeholder="如: 江苏省" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="城市">
                <el-input v-model="form.location.city" placeholder="如: 南通市" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="区县">
                <el-input v-model="form.location.district" placeholder="如: 崇川区" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="16">
              <el-form-item label="详细地址">
                <el-input v-model="form.location.address" placeholder="如: 南通市崇川区XX路以东、XX路以南" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="经度">
                <el-input-number v-model="form.location.longitude" :precision="2" :step="0.01" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="纬度">
                <el-input-number v-model="form.location.latitude" :precision="2" :step="0.01" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 三、投资与规模 -->
          <el-divider content-position="left">三、投资与规模</el-divider>
          <el-row :gutter="24">
            <el-col :span="6">
              <el-form-item label="总投资(万元)" required>
                <el-input-number v-model="form['total_investment_万元']" :min="0" :precision="2" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="土建投资(万元)">
                <el-input-number v-model="form['civil_investment_万元']" :min="0" :precision="2" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="建筑面积(m²)">
                <el-input-number v-model="form.construction_area_m2" :min="0" :precision="2" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="占地面积(hm²)" required>
                <el-input-number v-model="form.land_area_hm2" :min="0" :precision="4" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 四、土石方工程量 -->
          <el-divider content-position="left">四、土石方工程量</el-divider>
          <el-row :gutter="24">
            <el-col :span="6">
              <el-form-item label="挖方量(m³)" required>
                <el-input-number v-model="form.earthwork.excavation_m3" :min="0" :precision="1" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="填方量(m³)" required>
                <el-input-number v-model="form.earthwork.fill_m3" :min="0" :precision="1" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="表土剥离(m³)">
                <el-input-number v-model="form.earthwork.topsoil_strip_m3" :min="0" :precision="1" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="表土回覆(m³)">
                <el-input-number v-model="form.earthwork.topsoil_backfill_m3" :min="0" :precision="1" :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 五、施工进度 -->
          <el-divider content-position="left">五、施工进度</el-divider>
          <el-row :gutter="24">
            <el-col :span="6">
              <el-form-item label="开工日期" required>
                <el-date-picker v-model="form.schedule.start_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="竣工日期" required>
                <el-date-picker v-model="form.schedule.end_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="方案报送日期">
                <el-date-picker v-model="form.schedule.plan_submit_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="工期(月)">
                <el-input-number v-model="form.schedule.construction_period_months" :min="1" :max="120" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 项目区自然概况 (VL 生成) -->
          <el-divider content-position="left">项目区自然概况</el-divider>
          <el-form-item label="现场描述" label-width="160px">
            <el-input
              v-model="form.site_desc"
              type="textarea"
              :rows="5"
              placeholder="由 AI 视觉模型根据图纸/照片自动生成，也可手动编辑"
            />
          </el-form-item>

          <!-- 六、防治分区 -->
          <el-divider content-position="left">六、防治分区</el-divider>
          <div v-for="(zone, i) in form.zones" :key="i"
            style="background: #fafbfc; border: 1px solid #ebeef5; border-radius: 4px; padding: 16px; margin-bottom: 12px; position: relative">
            <div style="position: absolute; top: 8px; right: 8px">
              <el-button type="danger" link size="small" @click="form.zones.splice(i, 1)" :disabled="form.zones.length <= 1">
                删除
              </el-button>
            </div>
            <el-row :gutter="16">
              <el-col :span="6">
                <el-form-item label="分区名称" label-width="100px">
                  <el-select v-model="zone.name" filterable allow-create style="width:100%"
                    placeholder="选择或输入">
                    <el-option label="建(构)筑物区" value="建(构)筑物区" />
                    <el-option label="道路广场区" value="道路广场区" />
                    <el-option label="绿化工程区" value="绿化工程区" />
                    <el-option label="施工生产生活区" value="施工生产生活区" />
                    <el-option label="临时堆土区" value="临时堆土区" />
                    <el-option label="道路及管线工程区" value="道路及管线工程区" />
                    <el-option label="取土场" value="取土场" />
                    <el-option label="弃渣场" value="弃渣场" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="面积(hm²)" label-width="100px">
                  <el-input-number v-model="zone.area_hm2" :min="0" :precision="4" :controls="false" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="挖方(m³)" label-width="90px">
                  <el-input-number v-model="zone.excavation_m3" :min="0" :controls="false" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="填方(m³)" label-width="90px">
                  <el-input-number v-model="zone.fill_m3" :min="0" :controls="false" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="说明" label-width="50px">
                  <el-input v-model="zone.description" placeholder="分区说明" />
                </el-form-item>
              </el-col>
            </el-row>
          </div>
          <el-button type="primary" link @click="addZone">+ 添加分区</el-button>

          <!-- 七、水土保持指标 -->
          <el-divider content-position="left">七、水土保持指标</el-divider>
          <el-row :gutter="24">
            <el-col :span="8">
              <el-form-item label="防治标准等级" required>
                <el-select v-model="form.prevention_level" style="width: 100%">
                  <el-option label="一级" value="一级" />
                  <el-option label="二级" value="二级" />
                  <el-option label="三级" value="三级" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="设计水平年">
                <el-input-number v-model="form.design_level_year" :min="2020" :max="2050" style="width:100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="容许土壤流失量">
                <el-input-number v-model="form.allowable_erosion_modulus" :min="0" style="width:100%">
                  <template #append>t/(km²·a)</template>
                </el-input-number>
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="24">
            <el-col :span="8">
              <el-form-item label="地貌类型">
                <el-select v-model="form.landscape_type" style="width: 100%" filterable allow-create>
                  <el-option label="平原沙土区" value="平原沙土区" />
                  <el-option label="丘陵区" value="丘陵区" />
                  <el-option label="山区" value="山区" />
                  <el-option label="黄土高原区" value="黄土高原区" />
                  <el-option label="风沙区" value="风沙区" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="侵蚀类型">
                <el-select v-model="form.soil_erosion_type" style="width: 100%">
                  <el-option label="水力侵蚀" value="水力侵蚀" />
                  <el-option label="风力侵蚀" value="风力侵蚀" />
                  <el-option label="重力侵蚀" value="重力侵蚀" />
                  <el-option label="冻融侵蚀" value="冻融侵蚀" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="有取土场">
                <el-switch v-model="form.has_borrow_area" />
              </el-form-item>
            </el-col>
            <el-col :span="4">
              <el-form-item label="有弃渣场">
                <el-switch v-model="form.has_spoil_area" />
              </el-form-item>
            </el-col>
          </el-row>

          <!-- 八、防治目标 -->
          <el-divider content-position="left">八、防治目标 (%)</el-divider>
          <el-row :gutter="24">
            <el-col :span="4" v-for="(val, key) in form.prevention_targets" :key="key">
              <el-form-item :label="key" label-width="auto" style="margin-bottom: 12px">
                <el-input-number v-model="form.prevention_targets[key]" :min="0" :max="100"
                  :precision="key === '土壤流失控制比' ? 1 : 0"
                  :step="key === '土壤流失控制比' ? 0.1 : 1"
                  :controls="false" style="width:100%" />
              </el-form-item>
            </el-col>
          </el-row>

        </el-form>
      </div>

      <!-- ========== Step 2: 报告辅助生成 ========== -->
      <div v-if="wizardStep === 1" style="max-width: 900px; margin: 0 auto">
        <run-progress-inner :run-id="currentRunId" @done="onRunDone" @error="onRunError" />
      </div>

      <!-- ========== Step 3: 报告预览导出 (跳转到 Result 页) ========== -->
      <div v-if="wizardStep === 2" style="text-align: center; padding-top: 60px">
        <el-result icon="success" title="报告生成完成">
          <template #sub-title>点击下方按钮查看报告预览</template>
          <template #extra>
            <el-button type="primary" size="large" @click="$router.push(`/result/${currentRunId}`)">
              查看报告预览
            </el-button>
          </template>
        </el-result>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div style="padding: 12px 40px; border-top: 1px solid #e4e7ed; background: #fff; display: flex; justify-content: space-between; align-items: center">
      <div style="color: #909399; font-size: 13px">
        <span v-if="wizardStep === 0">已填写 {{ filledCount }} / {{ totalFields }} 项</span>
        <span v-else-if="wizardStep === 1">报告生成中...</span>
        <span v-else>报告已就绪</span>
      </div>
      <div>
        <el-button v-if="wizardStep === 0" @click="saveToServer" :loading="saving">保存配置</el-button>
        <el-button v-if="wizardStep === 0" type="primary" @click="startGenerate" :loading="starting">
          开始生成报告
        </el-button>
        <el-button v-if="wizardStep === 0" @click="startGenerate(true)" :loading="starting">
          跳过LLM (仅计算)
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Upload, MagicStick, Picture } from '@element-plus/icons-vue'
import {
  createRun, getFacts, updateFacts, validateConfig,
  uploadDocuments, vlExtractInfo, vlGenerateSiteDesc,
  listUploadedFiles, clearUploadedFiles, loadSampleData, vlHealthCheck,
  cadConvert, gisValidateZones, gisExtractZones,
} from '../api/index.js'
import { ElMessage, ElMessageBox } from 'element-plus'
import RunProgressInner from '../components/RunProgressInner.vue'

const router = useRouter()
const wizardStep = ref(0)
const currentRunId = ref(null)
const loadingFacts = ref(false)
const saving = ref(false)
const starting = ref(false)

// ── VL 相关 ──
const uploadedFiles = ref([])
const fileCategories = ref({})
const extracting = ref(false)
const generatingSiteDesc = ref(false)
const loadingSample = ref(false)
const vlStatus = ref(null)
const uploadRef = ref(null)
const convertingCad = ref(false)
const extractingGis = ref(false)
const validatingGis = ref(false)
const gisValidation = ref(null)

// ── 表单数据结构 (与 facts_v2.json 一致) ──
const form = reactive({
  project_name: '',
  investor: '',
  location: { province: '', city: '', district: '', address: '', longitude: 120.0, latitude: 30.0 },
  project_nature: '新建',
  project_type: '房地产',
  approval_level: '市级',
  'total_investment_万元': 0,
  'civil_investment_万元': 0,
  construction_area_m2: 0,
  land_area_hm2: 0,
  earthwork: { excavation_m3: 0, fill_m3: 0, topsoil_strip_m3: 0, topsoil_backfill_m3: 0 },
  schedule: { start_date: '', end_date: '', plan_submit_date: '', construction_period_months: 24 },
  zones: [{ name: '', area_hm2: 0, excavation_m3: 0, fill_m3: 0, description: '' }],
  prevention_level: '一级',
  design_level_year: 2026,
  landscape_type: '平原沙土区',
  soil_erosion_type: '水力侵蚀',
  allowable_erosion_modulus: 500,
  prevention_targets: {
    '水土流失治理度': 95,
    '土壤流失控制比': 1.0,
    '渣土防护率': 95,
    '表土保护率': 97,
    '林草植被恢复率': 97,
    '林草覆盖率': 27,
  },
  has_borrow_area: false,
  has_spoil_area: false,
  site_desc: '',
})

const totalFields = 12
const filledCount = computed(() => {
  let n = 0
  if (form.project_name) n++
  if (form.investor) n++
  if (form.location.province) n++
  if (form.location.city) n++
  if (form['total_investment_万元'] > 0) n++
  if (form.land_area_hm2 > 0) n++
  if (form.earthwork.excavation_m3 > 0) n++
  if (form.earthwork.fill_m3 > 0) n++
  if (form.schedule.start_date) n++
  if (form.schedule.end_date) n++
  if (form.zones.length > 0 && form.zones[0].name) n++
  if (form.prevention_level) n++
  return n
})

function addZone() {
  form.zones.push({ name: '', area_hm2: 0, excavation_m3: 0, fill_m3: 0, description: '' })
}

function deepAssign(target, source) {
  for (const key in source) {
    if (source[key] !== null && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      if (!target[key]) target[key] = {}
      deepAssign(target[key], source[key])
    } else {
      target[key] = source[key]
    }
  }
}

// ── 文件上传相关 ──

const hasCadFiles = computed(() =>
  uploadedFiles.value.some(f => /\.(dwg|dxf)$/i.test(f.name))
)
const hasGisFiles = computed(() =>
  uploadedFiles.value.some(f => /\.(shp|geojson|gpkg)$/i.test(f.name))
)

function getFileTagType(name) {
  const ext = name.split('.').pop().toLowerCase()
  if (['jpg', 'jpeg', 'png', 'bmp'].includes(ext)) return ''
  if (ext === 'pdf') return 'warning'
  if (['dwg', 'dxf'].includes(ext)) return 'danger'
  if (['shp', 'geojson', 'gpkg', 'shx', 'dbf', 'prj'].includes(ext)) return 'success'
  if (['doc', 'docx'].includes(ext)) return 'info'
  return 'info'
}

async function onFileChange(file) {
  // 逐个上传到后端
  try {
    const { data } = await uploadDocuments([file.raw], 'default')
    // 刷新文件列表
    await refreshFileList()
    ElMessage.success(`已上传: ${file.name}`)
  } catch (e) {
    ElMessage.error('上传失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function refreshFileList() {
  try {
    const { data } = await listUploadedFiles('default')
    uploadedFiles.value = data.files || []
    fileCategories.value = data.categories || {}
  } catch (e) {
    // ignore
  }
}

async function removeFile(name) {
  // 目前简化处理: 清空全部后重新上传
  // TODO: 单文件删除 API
  uploadedFiles.value = uploadedFiles.value.filter(f => f.name !== name)
}

async function clearFiles() {
  try {
    await clearUploadedFiles('default')
    uploadedFiles.value = []
    fileCategories.value = {}
    ElMessage.success('已清空上传文件')
  } catch (e) {
    ElMessage.error('清空失败')
  }
}

async function loadSample() {
  loadingSample.value = true
  try {
    const { data } = await loadSampleData('金石博雅园')
    await refreshFileList()
    ElMessage.success(`已加载样本数据: ${data.copied} 个文件`)
  } catch (e) {
    ElMessage.error('加载样本失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingSample.value = false
  }
}

async function runExtract() {
  if (uploadedFiles.value.length === 0) {
    ElMessage.warning('请先上传项目文档')
    return
  }
  extracting.value = true
  try {
    const { data } = await vlExtractInfo('default')
    if (data.extracted && Object.keys(data.extracted).length > 0) {
      // 将提取结果合并到表单 (仅填充非空字段)
      const extracted = data.extracted
      mergeExtracted(extracted)
      ElMessage.success(`AI 提取成功，已自动填入 ${Object.keys(extracted).length} 个字段`)
    } else {
      ElMessage.warning('AI 未能从文档中提取到有效信息')
    }
  } catch (e) {
    const msg = e.response?.data?.detail || e.message
    if (msg.includes('不可达') || msg.includes('Connection')) {
      ElMessage.error('VL 视觉模型未连接，请确保模型已启动 (端口 8001)')
    } else {
      ElMessage.error('提取失败: ' + msg)
    }
  } finally {
    extracting.value = false
  }
}

function mergeExtracted(extracted) {
  // 合并提取到的信息到表单 (只覆盖非空字段)
  if (extracted.project_name) form.project_name = extracted.project_name
  if (extracted.investor) form.investor = extracted.investor
  if (extracted.project_nature) form.project_nature = extracted.project_nature
  if (extracted.project_type) form.project_type = extracted.project_type

  if (extracted.location) {
    if (extracted.location.province) form.location.province = extracted.location.province
    if (extracted.location.city) form.location.city = extracted.location.city
    if (extracted.location.district) form.location.district = extracted.location.district
    if (extracted.location.address) form.location.address = extracted.location.address
  }

  if (extracted['total_investment_万元']) form['total_investment_万元'] = extracted['total_investment_万元']
  if (extracted['civil_investment_万元']) form['civil_investment_万元'] = extracted['civil_investment_万元']
  if (extracted.construction_area_m2) form.construction_area_m2 = extracted.construction_area_m2
  if (extracted.land_area_hm2) form.land_area_hm2 = extracted.land_area_hm2

  if (extracted.earthwork) {
    if (extracted.earthwork.excavation_m3) form.earthwork.excavation_m3 = extracted.earthwork.excavation_m3
    if (extracted.earthwork.fill_m3) form.earthwork.fill_m3 = extracted.earthwork.fill_m3
  }

  if (extracted.schedule) {
    if (extracted.schedule.start_date) form.schedule.start_date = extracted.schedule.start_date
    if (extracted.schedule.end_date) form.schedule.end_date = extracted.schedule.end_date
    if (extracted.schedule.construction_period_months) {
      form.schedule.construction_period_months = extracted.schedule.construction_period_months
    }
  }
}

async function runSiteDesc() {
  if (uploadedFiles.value.length === 0) {
    ElMessage.warning('请先上传项目文档')
    return
  }
  generatingSiteDesc.value = true
  try {
    const { data } = await vlGenerateSiteDesc('default')
    if (data.site_desc) {
      form.site_desc = data.site_desc
      ElMessage.success('AI 已生成项目现场描述')
    } else {
      ElMessage.warning('AI 未能生成有效描述')
    }
  } catch (e) {
    const msg = e.response?.data?.detail || e.message
    if (msg.includes('不可达') || msg.includes('Connection')) {
      ElMessage.error('VL 视觉模型未连接，请确保模型已启动 (端口 8001)')
    } else {
      ElMessage.error('生成失败: ' + msg)
    }
  } finally {
    generatingSiteDesc.value = false
  }
}

// ── CAD / GIS 功能 ──

async function runCadConvert() {
  convertingCad.value = true
  try {
    const { data } = await cadConvert('default')
    if (data.converted > 0) {
      ElMessage.success(`CAD 转换成功: ${data.converted} 个文件已转为 PNG`)
      await refreshFileList()
    } else {
      const errMsg = data.error_details?.[0]?.message || '转换失败'
      ElMessage.error('CAD 转换失败: ' + errMsg)
    }
  } catch (e) {
    ElMessage.error('CAD 转换失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    convertingCad.value = false
  }
}

async function runGisExtract() {
  extractingGis.value = true
  try {
    const { data } = await gisExtractZones('default')
    if (data.zones && data.zones.length > 0) {
      await ElMessageBox.confirm(
        `GIS 提取到 ${data.zones.length} 个分区 (总面积 ${data.total_area_hm2} hm²)。\n是否替换当前表单中的分区数据？`,
        'GIS 分区导入',
        { confirmButtonText: '替换', cancelButtonText: '取消', type: 'info' }
      )
      form.zones = data.zones
      // 同步总面积
      form.land_area_hm2 = data.total_area_hm2
      ElMessage.success(`已导入 ${data.zones.length} 个分区`)
    } else {
      ElMessage.warning('GIS 文件中未提取到有效分区数据')
    }
  } catch (e) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) return
    ElMessage.error('GIS 导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    extractingGis.value = false
  }
}

async function runGisValidate() {
  validatingGis.value = true
  gisValidation.value = null
  try {
    const { data } = await gisValidateZones('default')
    if (data.validation) {
      gisValidation.value = data.validation
      if (data.validation.valid) {
        ElMessage.success('GIS 面积校验通过')
      } else {
        ElMessage.warning('GIS 面积校验不通过，请检查偏差详情')
      }
    } else {
      ElMessage.info(`GIS 提取到 ${data.gis_zones?.length || 0} 个分区 (facts 中无分区数据可比对)`)
    }
  } catch (e) {
    ElMessage.error('GIS 校验失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    validatingGis.value = false
  }
}

// ── 原有功能 ──

async function loadServerFacts() {
  loadingFacts.value = true
  try {
    const { data } = await getFacts()
    deepAssign(form, data)
    if (data.zones) form.zones = data.zones
    if (data.prevention_targets) {
      for (const k in data.prevention_targets) {
        form.prevention_targets[k] = data.prevention_targets[k]
      }
    }
    ElMessage.success('已加载服务端配置')
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingFacts.value = false
  }
}

async function importJSON(file) {
  try {
    const text = await file.raw.text()
    const data = JSON.parse(text)
    deepAssign(form, data)
    if (data.zones) form.zones = data.zones
    if (data.prevention_targets) {
      for (const k in data.prevention_targets) {
        form.prevention_targets[k] = data.prevention_targets[k]
      }
    }
    ElMessage.success('已导入 JSON')
  } catch (e) {
    ElMessage.error('JSON 解析失败: ' + e.message)
  }
}

async function saveToServer() {
  saving.value = true
  try {
    await updateFacts(JSON.parse(JSON.stringify(form)))
    ElMessage.success('配置已保存到服务端')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function startGenerate(noLlm = false) {
  if (!form.project_name) { ElMessage.warning('请填写项目名称'); return }
  if (!form.investor) { ElMessage.warning('请填写建设单位'); return }
  if (form.land_area_hm2 <= 0) { ElMessage.warning('请填写占地面积'); return }
  if (!form.zones.length || !form.zones[0].name) { ElMessage.warning('请至少添加一个防治分区'); return }

  starting.value = true
  try {
    await updateFacts(JSON.parse(JSON.stringify(form)))
    const { data } = await createRun({ use_llm: noLlm !== true })
    currentRunId.value = data.id
    wizardStep.value = 1
  } catch (e) {
    ElMessage.error('启动失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    starting.value = false
  }
}

function onRunDone() {
  wizardStep.value = 2
}

function onRunError() {
  ElMessage.error('报告生成失败，请检查日志')
}

async function checkVlHealth() {
  try {
    const { data } = await vlHealthCheck()
    vlStatus.value = data.vl_reachable ? 'ok' : 'error'
  } catch {
    vlStatus.value = 'error'
  }
}

onMounted(() => {
  loadServerFacts()
  refreshFileList()
  checkVlHealth()
})
</script>
