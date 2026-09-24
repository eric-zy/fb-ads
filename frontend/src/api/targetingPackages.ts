import request from '@/utils/request'

export interface RegionGroup {
  id: string
  name: string
  geo_locations: Record<string, any>
  excluded_geo_locations: Record<string, any>
  account_ids: string[]
  status: string
  description?: string | null
}

export interface TargetingPackage {
  id: string
  name: string
  targeting_json: Record<string, any>
  placement_json: Record<string, any>
  account_ids: string[]
  region_group_ids: string[]
  status: string
  description?: string | null
}

export const regionGroupsApi = {
  list: (status = 'ACTIVE') => request.get<RegionGroup[]>('/api/v1/region-groups', { params: { status } }),
  create: (payload: Omit<RegionGroup, 'id' | 'status'>) => request.post<RegionGroup>('/api/v1/region-groups', payload),
  update: (id: string, payload: Omit<RegionGroup, 'id' | 'status'>) => request.put<RegionGroup>(`/api/v1/region-groups/${id}`, payload),
  remove: (id: string) => request.delete(`/api/v1/region-groups/${id}`),
}

export const targetingPackagesApi = {
  list: (status = 'ACTIVE') => request.get<TargetingPackage[]>('/api/v1/targeting-packages', { params: { status } }),
  create: (payload: Omit<TargetingPackage, 'id' | 'status'>) => request.post<TargetingPackage>('/api/v1/targeting-packages', payload),
  update: (id: string, payload: Omit<TargetingPackage, 'id' | 'status'>) => request.put<TargetingPackage>(`/api/v1/targeting-packages/${id}`, payload),
  remove: (id: string) => request.delete(`/api/v1/targeting-packages/${id}`),
}
