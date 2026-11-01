import request from '@/utils/request'
import { createAuditApi } from './auditClient'

export const auditApi = createAuditApi(request)
