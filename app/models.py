from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class RegisterOptionsRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    display_name: Optional[str] = Field(None, max_length=50, description="显示名称")

class RegisterVerifyRequest(BaseModel):
    challenge_id: str
    credential: Dict[str, Any]
    device_name: Optional[str] = Field("我的设备", max_length=100)

class LoginOptionsRequest(BaseModel):
    username: Optional[str] = None

class LoginVerifyRequest(BaseModel):
    challenge_id: str
    credential: Dict[str, Any]

class AssetCreateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=100, description="资产编号/唯一识别码")
    name: str = Field(..., min_length=1, max_length=200, description="资产名称")
    location: str = Field(..., min_length=1, max_length=200, description="存放/所在位置")
    category: Optional[str] = Field("通用", max_length=100, description="资产类别")
    status: Optional[str] = Field("在用", max_length=50, description="资产状态")
    description: Optional[str] = Field("", max_length=2000, description="备注或规格说明")
    parent_id: Optional[str] = Field(None, max_length=100, description="所属父设备编号")

class AssetUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=2000)
    parent_id: Optional[str] = Field(None, max_length=100)

class TranslationRuleRequest(BaseModel):
    prefix: str = Field(..., min_length=1, max_length=20, description="ID前缀 (如 CPR, PU)")
    name_prefix: str = Field(..., min_length=1, max_length=100, description="翻译后的设备名称 (如 Capper, Pump)")
    example_id: Optional[str] = Field(None, max_length=100)
    example_name: Optional[str] = Field(None, max_length=200)

class RenamePasskeyRequest(BaseModel):
    passkey_id: str
    device_name: str = Field(..., min_length=1, max_length=100)

