-- EduVault production schema for MySQL 8.4
-- Files and embeddings are stored outside MySQL; this schema stores metadata,
-- access control, object locations, RAG lineage, audit, and operations data.
-- One-time bootstrap: run on an empty eduvault_v2 schema.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET time_zone = '+00:00';

CREATE DATABASE IF NOT EXISTS eduvault_v2
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE eduvault_v2;

CREATE TABLE departments (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  parent_id BIGINT UNSIGNED NULL,
  code VARCHAR(50) NOT NULL,
  name VARCHAR(255) NOT NULL,
  department_type ENUM('university','faculty','department','division','center') NOT NULL,
  path_cache VARCHAR(1500) NULL COMMENT 'Read cache only; parent_id is authoritative',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  deleted_by BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_departments_public_id (public_id),
  UNIQUE KEY uq_departments_code (code),
  KEY idx_departments_parent (parent_id, is_active),
  CONSTRAINT fk_departments_parent FOREIGN KEY (parent_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  employee_code VARCHAR(50) NOT NULL,
  primary_department_id BIGINT UNSIGNED NULL,
  email VARCHAR(320) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NULL COMMENT 'Null when SSO-only',
  identity_provider VARCHAR(50) NULL,
  identity_subject VARCHAR(255) NULL,
  status ENUM('invited','active','suspended','disabled') NOT NULL DEFAULT 'active',
  locale VARCHAR(20) NOT NULL DEFAULT 'vi-VN',
  last_login_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  deleted_by BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_public_id (public_id),
  UNIQUE KEY uq_users_employee_code (employee_code),
  UNIQUE KEY uq_users_email (email),
  UNIQUE KEY uq_users_identity (identity_provider, identity_subject),
  KEY idx_users_department_status (primary_department_id, status),
  CONSTRAINT fk_users_primary_department FOREIGN KEY (primary_department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

ALTER TABLE departments
  ADD CONSTRAINT fk_departments_deleted_by FOREIGN KEY (deleted_by) REFERENCES users(id);
ALTER TABLE users
  ADD CONSTRAINT fk_users_deleted_by FOREIGN KEY (deleted_by) REFERENCES users(id);

CREATE TABLE user_department_memberships (
  user_id BIGINT UNSIGNED NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  membership_type ENUM('primary','secondary','visiting') NOT NULL DEFAULT 'secondary',
  starts_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ends_at DATETIME(6) NULL,
  PRIMARY KEY (user_id, department_id),
  KEY idx_memberships_department (department_id, ends_at),
  CONSTRAINT fk_memberships_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_memberships_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE roles (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(150) NOT NULL,
  description VARCHAR(1000) NULL,
  is_system BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_code (code)
) ENGINE=InnoDB;

CREATE TABLE permissions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(120) NOT NULL,
  resource_type VARCHAR(80) NOT NULL,
  action VARCHAR(80) NOT NULL,
  description VARCHAR(1000) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_permissions_code (code),
  UNIQUE KEY uq_permissions_resource_action (resource_type, action)
) ENGINE=InnoDB;

CREATE TABLE role_permissions (
  role_id BIGINT UNSIGNED NOT NULL,
  permission_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (role_id, permission_id),
  CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id),
  CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id) REFERENCES permissions(id)
) ENGINE=InnoDB;

CREATE TABLE user_roles (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  role_id BIGINT UNSIGNED NOT NULL,
  department_id BIGINT UNSIGNED NULL COMMENT 'Null means university-wide scope',
  scope_department_id BIGINT UNSIGNED GENERATED ALWAYS AS (IFNULL(department_id, 0)) STORED,
  granted_by BIGINT UNSIGNED NULL,
  granted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expires_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_roles_scope (user_id, role_id, scope_department_id),
  KEY idx_user_roles_authorization (user_id, department_id, expires_at),
  KEY idx_user_roles_role_scope (role_id, department_id),
  CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id) REFERENCES roles(id),
  CONSTRAINT fk_user_roles_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_user_roles_granted_by FOREIGN KEY (granted_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE subjects (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  code VARCHAR(50) NOT NULL,
  name VARCHAR(255) NOT NULL,
  credits DECIMAL(4,1) NULL,
  description TEXT NULL,
  status ENUM('draft','active','retired') NOT NULL DEFAULT 'active',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_subjects_public_id (public_id),
  UNIQUE KEY uq_subjects_code (code),
  KEY idx_subjects_department_status (department_id, status),
  CONSTRAINT fk_subjects_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE courses (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  subject_id BIGINT UNSIGNED NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  academic_year VARCHAR(20) NOT NULL,
  term VARCHAR(30) NOT NULL,
  section_code VARCHAR(50) NOT NULL,
  lecturer_id BIGINT UNSIGNED NULL,
  starts_on DATE NULL,
  ends_on DATE NULL,
  status ENUM('planned','active','completed','archived') NOT NULL DEFAULT 'planned',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_courses_public_id (public_id),
  UNIQUE KEY uq_courses_offering (subject_id, academic_year, term, section_code),
  KEY idx_courses_department_term (department_id, academic_year, term, status),
  KEY idx_courses_lecturer (lecturer_id, status),
  CONSTRAINT fk_courses_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
  CONSTRAINT fk_courses_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_courses_lecturer FOREIGN KEY (lecturer_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE folders (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  parent_id BIGINT UNSIGNED NULL,
  parent_scope_id BIGINT UNSIGNED GENERATED ALWAYS AS (IFNULL(parent_id, 0)) STORED,
  name VARCHAR(255) NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  owner_id BIGINT UNSIGNED NOT NULL,
  inherit_permissions BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  deleted_by BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_folders_public_id (public_id),
  UNIQUE KEY uq_folders_sibling_name (department_id, parent_scope_id, name),
  KEY idx_folders_parent (parent_id, deleted_at),
  KEY idx_folders_owner (owner_id, deleted_at),
  CONSTRAINT fk_folders_parent FOREIGN KEY (parent_id) REFERENCES folders(id),
  CONSTRAINT fk_folders_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_folders_owner FOREIGN KEY (owner_id) REFERENCES users(id),
  CONSTRAINT fk_folders_deleted_by FOREIGN KEY (deleted_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE folder_closure (
  ancestor_id BIGINT UNSIGNED NOT NULL,
  descendant_id BIGINT UNSIGNED NOT NULL,
  depth SMALLINT UNSIGNED NOT NULL,
  PRIMARY KEY (ancestor_id, descendant_id),
  KEY idx_folder_closure_descendant (descendant_id, depth),
  CONSTRAINT fk_folder_closure_ancestor FOREIGN KEY (ancestor_id) REFERENCES folders(id) ON DELETE CASCADE,
  CONSTRAINT fk_folder_closure_descendant FOREIGN KEY (descendant_id) REFERENCES folders(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE document_types (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(80) NOT NULL,
  name VARCHAR(150) NOT NULL,
  retention_class VARCHAR(80) NOT NULL,
  requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (id),
  UNIQUE KEY uq_document_types_code (code)
) ENGINE=InnoDB;

CREATE TABLE documents (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  folder_id BIGINT UNSIGNED NULL,
  subject_id BIGINT UNSIGNED NULL,
  course_id BIGINT UNSIGNED NULL,
  document_type_id SMALLINT UNSIGNED NOT NULL,
  owner_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(500) NOT NULL,
  description TEXT NULL,
  classification ENUM('public','internal','confidential','restricted') NOT NULL DEFAULT 'internal',
  lifecycle_status ENUM('draft','review','published','archived') NOT NULL DEFAULT 'draft',
  current_version_id BIGINT UNSIGNED NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  published_at DATETIME(6) NULL,
  deleted_at DATETIME(6) NULL,
  deleted_by BIGINT UNSIGNED NULL,
  legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (id),
  UNIQUE KEY uq_documents_public_id (public_id),
  KEY idx_documents_department_updated (department_id, deleted_at, updated_at DESC),
  KEY idx_documents_folder_updated (folder_id, deleted_at, updated_at DESC),
  KEY idx_documents_owner_updated (owner_id, deleted_at, updated_at DESC),
  KEY idx_documents_course (course_id, lifecycle_status, deleted_at),
  KEY idx_documents_subject (subject_id, lifecycle_status, deleted_at),
  KEY idx_documents_classification (classification, lifecycle_status, deleted_at),
  FULLTEXT KEY ftx_documents_title_description (title, description),
  CONSTRAINT fk_documents_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_documents_folder FOREIGN KEY (folder_id) REFERENCES folders(id),
  CONSTRAINT fk_documents_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
  CONSTRAINT fk_documents_course FOREIGN KEY (course_id) REFERENCES courses(id),
  CONSTRAINT fk_documents_type FOREIGN KEY (document_type_id) REFERENCES document_types(id),
  CONSTRAINT fk_documents_owner FOREIGN KEY (owner_id) REFERENCES users(id),
  CONSTRAINT fk_documents_deleted_by FOREIGN KEY (deleted_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE document_versions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  document_id BIGINT UNSIGNED NOT NULL,
  version_no INT UNSIGNED NOT NULL,
  parent_version_id BIGINT UNSIGNED NULL,
  rollback_from_version_id BIGINT UNSIGNED NULL,
  created_by BIGINT UNSIGNED NOT NULL,
  change_summary VARCHAR(1000) NULL,
  content_sha256 BINARY(32) NOT NULL,
  mime_type VARCHAR(255) NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  extraction_status ENUM('pending','processing','completed','failed') NOT NULL DEFAULT 'pending',
  indexing_status ENUM('pending','processing','completed','failed') NOT NULL DEFAULT 'pending',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_document_versions_public_id (public_id),
  UNIQUE KEY uq_document_versions_number (document_id, version_no),
  UNIQUE KEY uq_document_versions_document_id (document_id, id),
  KEY idx_document_versions_created (document_id, created_at DESC),
  KEY idx_document_versions_parent (parent_version_id),
  KEY idx_document_versions_rollback (rollback_from_version_id),
  CONSTRAINT fk_document_versions_document FOREIGN KEY (document_id) REFERENCES documents(id),
  CONSTRAINT fk_document_versions_parent FOREIGN KEY (parent_version_id) REFERENCES document_versions(id),
  CONSTRAINT fk_document_versions_rollback FOREIGN KEY (rollback_from_version_id) REFERENCES document_versions(id),
  CONSTRAINT fk_document_versions_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB;

ALTER TABLE documents
  ADD CONSTRAINT fk_documents_current_version
    FOREIGN KEY (id, current_version_id) REFERENCES document_versions(document_id, id);

CREATE TABLE storage_locations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  department_id BIGINT UNSIGNED NULL,
  name VARCHAR(255) NOT NULL,
  provider ENUM('local','nas','google_drive','onedrive','s3') NOT NULL,
  storage_tier ENUM('hot','warm','cold','archive') NOT NULL DEFAULT 'hot',
  region VARCHAR(100) NULL,
  endpoint VARCHAR(1000) NULL,
  bucket_or_root VARCHAR(1000) NOT NULL,
  config_encrypted LONGBLOB NULL,
  encryption_key_ref VARCHAR(500) NULL,
  is_offsite BOOLEAN NOT NULL DEFAULT FALSE,
  is_immutable BOOLEAN NOT NULL DEFAULT FALSE,
  status ENUM('active','degraded','disabled') NOT NULL DEFAULT 'active',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_storage_locations_public_id (public_id),
  KEY idx_storage_locations_policy (provider, storage_tier, is_offsite, status),
  CONSTRAINT fk_storage_locations_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE document_version_objects (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_version_id BIGINT UNSIGNED NOT NULL,
  storage_location_id BIGINT UNSIGNED NOT NULL,
  object_key VARCHAR(2000) NOT NULL,
  provider_object_id VARCHAR(1000) NULL,
  object_kind ENUM('original','extracted_text','preview','thumbnail','ocr_output') NOT NULL,
  content_sha256 BINARY(32) NOT NULL,
  size_bytes BIGINT UNSIGNED NOT NULL,
  encryption_status ENUM('none','provider_managed','customer_managed') NOT NULL DEFAULT 'provider_managed',
  replica_status ENUM('pending','available','failed','deleted') NOT NULL DEFAULT 'pending',
  verified_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_version_object (document_version_id, storage_location_id, object_kind),
  KEY idx_version_objects_location_status (storage_location_id, replica_status, verified_at),
  KEY idx_version_objects_hash (content_sha256),
  CONSTRAINT fk_version_objects_version FOREIGN KEY (document_version_id) REFERENCES document_versions(id),
  CONSTRAINT fk_version_objects_location FOREIGN KEY (storage_location_id) REFERENCES storage_locations(id)
) ENGINE=InnoDB;

CREATE TABLE metadata_definitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(120) NOT NULL,
  name VARCHAR(255) NOT NULL,
  value_type ENUM('string','text','number','boolean','date','datetime','json') NOT NULL,
  is_required BOOLEAN NOT NULL DEFAULT FALSE,
  is_searchable BOOLEAN NOT NULL DEFAULT FALSE,
  validation_schema JSON NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_metadata_definitions_code (code)
) ENGINE=InnoDB;

CREATE TABLE document_metadata (
  document_id BIGINT UNSIGNED NOT NULL,
  definition_id BIGINT UNSIGNED NOT NULL,
  value_string VARCHAR(2000) NULL,
  value_text LONGTEXT NULL,
  value_number DECIMAL(30,10) NULL,
  value_boolean BOOLEAN NULL,
  value_datetime DATETIME(6) NULL,
  value_json JSON NULL,
  updated_by BIGINT UNSIGNED NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (document_id, definition_id),
  KEY idx_document_metadata_string (definition_id, value_string(255)),
  KEY idx_document_metadata_datetime (definition_id, value_datetime),
  CONSTRAINT fk_document_metadata_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  CONSTRAINT fk_document_metadata_definition FOREIGN KEY (definition_id) REFERENCES metadata_definitions(id),
  CONSTRAINT fk_document_metadata_updated_by FOREIGN KEY (updated_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE tags (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  department_id BIGINT UNSIGNED NULL,
  scope_department_id BIGINT UNSIGNED GENERATED ALWAYS AS (IFNULL(department_id, 0)) STORED,
  name VARCHAR(120) NOT NULL,
  normalized_name VARCHAR(120) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_tags_scope_name (scope_department_id, normalized_name),
  CONSTRAINT fk_tags_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE document_tags (
  document_id BIGINT UNSIGNED NOT NULL,
  tag_id BIGINT UNSIGNED NOT NULL,
  assigned_by BIGINT UNSIGNED NOT NULL,
  assigned_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (document_id, tag_id),
  KEY idx_document_tags_tag (tag_id, document_id),
  CONSTRAINT fk_document_tags_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  CONSTRAINT fk_document_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(id),
  CONSTRAINT fk_document_tags_assigned_by FOREIGN KEY (assigned_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE document_permissions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  document_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  role_id BIGINT UNSIGNED NULL,
  can_read BOOLEAN NOT NULL DEFAULT FALSE,
  can_edit BOOLEAN NOT NULL DEFAULT FALSE,
  can_delete BOOLEAN NOT NULL DEFAULT FALSE,
  can_share BOOLEAN NOT NULL DEFAULT FALSE,
  granted_by BIGINT UNSIGNED NOT NULL,
  granted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expires_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_document_permissions_user (document_id, user_id),
  UNIQUE KEY uq_document_permissions_role (document_id, role_id),
  KEY idx_document_permissions_user_lookup (user_id, document_id, expires_at),
  KEY idx_document_permissions_role_lookup (role_id, document_id, expires_at),
  CONSTRAINT chk_document_permissions_grantee CHECK ((user_id IS NULL) <> (role_id IS NULL)),
  CONSTRAINT fk_document_permissions_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  CONSTRAINT fk_document_permissions_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_document_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id),
  CONSTRAINT fk_document_permissions_granted_by FOREIGN KEY (granted_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE folder_permissions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  folder_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  role_id BIGINT UNSIGNED NULL,
  can_read BOOLEAN NOT NULL DEFAULT FALSE,
  can_edit BOOLEAN NOT NULL DEFAULT FALSE,
  can_delete BOOLEAN NOT NULL DEFAULT FALSE,
  can_share BOOLEAN NOT NULL DEFAULT FALSE,
  granted_by BIGINT UNSIGNED NOT NULL,
  granted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expires_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_folder_permissions_user (folder_id, user_id),
  UNIQUE KEY uq_folder_permissions_role (folder_id, role_id),
  KEY idx_folder_permissions_user_lookup (user_id, folder_id, expires_at),
  KEY idx_folder_permissions_role_lookup (role_id, folder_id, expires_at),
  CONSTRAINT chk_folder_permissions_grantee CHECK ((user_id IS NULL) <> (role_id IS NULL)),
  CONSTRAINT fk_folder_permissions_folder FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE,
  CONSTRAINT fk_folder_permissions_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_folder_permissions_role FOREIGN KEY (role_id) REFERENCES roles(id),
  CONSTRAINT fk_folder_permissions_granted_by FOREIGN KEY (granted_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE access_requests (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  document_id BIGINT UNSIGNED NULL,
  folder_id BIGINT UNSIGNED NULL,
  requester_id BIGINT UNSIGNED NOT NULL,
  requested_permission ENUM('read','edit','share') NOT NULL,
  reason VARCHAR(2000) NULL,
  status ENUM('pending','approved','rejected','cancelled','expired') NOT NULL DEFAULT 'pending',
  decided_by BIGINT UNSIGNED NULL,
  requested_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  decided_at DATETIME(6) NULL,
  expires_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_access_requests_public_id (public_id),
  KEY idx_access_requests_requester (requester_id, status, requested_at DESC),
  KEY idx_access_requests_document (document_id, status, requested_at DESC),
  KEY idx_access_requests_folder (folder_id, status, requested_at DESC),
  CONSTRAINT chk_access_requests_resource CHECK ((document_id IS NULL) <> (folder_id IS NULL)),
  CONSTRAINT fk_access_requests_document FOREIGN KEY (document_id) REFERENCES documents(id),
  CONSTRAINT fk_access_requests_folder FOREIGN KEY (folder_id) REFERENCES folders(id),
  CONSTRAINT fk_access_requests_requester FOREIGN KEY (requester_id) REFERENCES users(id),
  CONSTRAINT fk_access_requests_decided_by FOREIGN KEY (decided_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE embedding_models (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  provider VARCHAR(80) NOT NULL,
  model_name VARCHAR(255) NOT NULL,
  dimensions SMALLINT UNSIGNED NOT NULL,
  distance_metric ENUM('cosine','dot_product','euclidean') NOT NULL DEFAULT 'cosine',
  status ENUM('active','deprecated','disabled') NOT NULL DEFAULT 'active',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_embedding_models (provider, model_name, dimensions)
) ENGINE=InnoDB;

CREATE TABLE document_chunks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  document_id BIGINT UNSIGNED NOT NULL,
  document_version_id BIGINT UNSIGNED NOT NULL,
  chunk_no INT UNSIGNED NOT NULL,
  content LONGTEXT NOT NULL,
  token_count INT UNSIGNED NOT NULL,
  page_from INT UNSIGNED NULL,
  page_to INT UNSIGNED NULL,
  heading_path VARCHAR(2000) NULL,
  language VARCHAR(20) NOT NULL DEFAULT 'vi',
  chunk_metadata JSON NULL,
  content_sha256 BINARY(32) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_document_chunks_public_id (public_id),
  UNIQUE KEY uq_document_chunks_number (document_version_id, chunk_no),
  KEY idx_document_chunks_document (document_id, document_version_id),
  FULLTEXT KEY ftx_document_chunks_content (content),
  CONSTRAINT fk_document_chunks_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  CONSTRAINT fk_document_chunks_version
    FOREIGN KEY (document_id, document_version_id)
    REFERENCES document_versions(document_id, id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE chunk_embeddings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  chunk_id BIGINT UNSIGNED NOT NULL,
  embedding_model_id BIGINT UNSIGNED NOT NULL,
  embedding LONGBLOB NULL COMMENT 'Float32 bytes; external vector DB is recommended at scale',
  vector_store_key VARCHAR(1000) NULL,
  indexed_at DATETIME(6) NULL,
  status ENUM('pending','indexed','failed','deleted') NOT NULL DEFAULT 'pending',
  error_message TEXT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_chunk_embeddings_model (chunk_id, embedding_model_id),
  KEY idx_chunk_embeddings_status (embedding_model_id, status, indexed_at),
  CONSTRAINT fk_chunk_embeddings_chunk FOREIGN KEY (chunk_id) REFERENCES document_chunks(id) ON DELETE CASCADE,
  CONSTRAINT fk_chunk_embeddings_model FOREIGN KEY (embedding_model_id) REFERENCES embedding_models(id)
) ENGINE=InnoDB;

CREATE TABLE retrieval_queries (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  user_id BIGINT UNSIGNED NULL,
  department_id BIGINT UNSIGNED NULL,
  query_hash BINARY(32) NOT NULL,
  query_text TEXT NULL COMMENT 'May be redacted by retention policy',
  filters JSON NULL,
  model_name VARCHAR(255) NULL,
  result_count INT UNSIGNED NOT NULL DEFAULT 0,
  latency_ms INT UNSIGNED NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_retrieval_queries_public_id (public_id),
  KEY idx_retrieval_queries_user_created (user_id, created_at DESC),
  KEY idx_retrieval_queries_department_created (department_id, created_at DESC),
  KEY idx_retrieval_queries_hash_created (query_hash, created_at DESC),
  CONSTRAINT fk_retrieval_queries_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_retrieval_queries_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE retrieval_results (
  query_id BIGINT UNSIGNED NOT NULL,
  rank_no SMALLINT UNSIGNED NOT NULL,
  chunk_id BIGINT UNSIGNED NOT NULL,
  score DECIMAL(12,9) NOT NULL,
  was_authorized BOOLEAN NOT NULL,
  was_used_in_answer BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (query_id, rank_no),
  KEY idx_retrieval_results_chunk (chunk_id, query_id),
  CONSTRAINT fk_retrieval_results_query FOREIGN KEY (query_id) REFERENCES retrieval_queries(id) ON DELETE CASCADE,
  CONSTRAINT fk_retrieval_results_chunk FOREIGN KEY (chunk_id) REFERENCES document_chunks(id)
) ENGINE=InnoDB;

CREATE TABLE citations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  query_id BIGINT UNSIGNED NOT NULL,
  document_id BIGINT UNSIGNED NOT NULL,
  document_version_id BIGINT UNSIGNED NOT NULL,
  chunk_id BIGINT UNSIGNED NULL,
  citation_order SMALLINT UNSIGNED NOT NULL,
  excerpt TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_citations_order (query_id, citation_order),
  KEY idx_citations_document (document_id, created_at DESC),
  CONSTRAINT fk_citations_query FOREIGN KEY (query_id) REFERENCES retrieval_queries(id) ON DELETE CASCADE,
  CONSTRAINT fk_citations_document FOREIGN KEY (document_id) REFERENCES documents(id),
  CONSTRAINT fk_citations_version
    FOREIGN KEY (document_id, document_version_id)
    REFERENCES document_versions(document_id, id),
  CONSTRAINT fk_citations_chunk FOREIGN KEY (chunk_id) REFERENCES document_chunks(id)
) ENGINE=InnoDB;

CREATE TABLE handover_packages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  department_id BIGINT UNSIGNED NOT NULL,
  subject_id BIGINT UNSIGNED NULL,
  course_id BIGINT UNSIGNED NULL,
  from_user_id BIGINT UNSIGNED NOT NULL,
  to_user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(500) NOT NULL,
  summary LONGTEXT NULL,
  status ENUM('draft','in_progress','submitted','accepted','rejected','completed','cancelled') NOT NULL DEFAULT 'draft',
  due_at DATETIME(6) NULL,
  submitted_at DATETIME(6) NULL,
  completed_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_handover_packages_public_id (public_id),
  KEY idx_handover_packages_from (from_user_id, status, due_at),
  KEY idx_handover_packages_to (to_user_id, status, due_at),
  KEY idx_handover_packages_department (department_id, status, due_at),
  CONSTRAINT fk_handover_packages_department FOREIGN KEY (department_id) REFERENCES departments(id),
  CONSTRAINT fk_handover_packages_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
  CONSTRAINT fk_handover_packages_course FOREIGN KEY (course_id) REFERENCES courses(id),
  CONSTRAINT fk_handover_packages_from FOREIGN KEY (from_user_id) REFERENCES users(id),
  CONSTRAINT fk_handover_packages_to FOREIGN KEY (to_user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE handover_documents (
  handover_package_id BIGINT UNSIGNED NOT NULL,
  document_id BIGINT UNSIGNED NOT NULL,
  required BOOLEAN NOT NULL DEFAULT TRUE,
  note VARCHAR(2000) NULL,
  PRIMARY KEY (handover_package_id, document_id),
  CONSTRAINT fk_handover_documents_package FOREIGN KEY (handover_package_id) REFERENCES handover_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_handover_documents_document FOREIGN KEY (document_id) REFERENCES documents(id)
) ENGINE=InnoDB;

CREATE TABLE handover_checklist_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  handover_package_id BIGINT UNSIGNED NOT NULL,
  item_order SMALLINT UNSIGNED NOT NULL,
  title VARCHAR(500) NOT NULL,
  description TEXT NULL,
  status ENUM('pending','completed','waived') NOT NULL DEFAULT 'pending',
  completed_by BIGINT UNSIGNED NULL,
  completed_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_handover_checklist_order (handover_package_id, item_order),
  CONSTRAINT fk_handover_checklist_package FOREIGN KEY (handover_package_id) REFERENCES handover_packages(id) ON DELETE CASCADE,
  CONSTRAINT fk_handover_checklist_completed_by FOREIGN KEY (completed_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE cloud_connections (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  provider ENUM('google_drive','onedrive') NOT NULL,
  account_email VARCHAR(320) NOT NULL,
  external_account_id VARCHAR(500) NULL,
  access_token_encrypted LONGBLOB NOT NULL,
  refresh_token_encrypted LONGBLOB NULL,
  token_expires_at DATETIME(6) NULL,
  scopes TEXT NULL,
  status ENUM('connected','expired','revoked','error') NOT NULL DEFAULT 'connected',
  last_sync_at DATETIME(6) NULL,
  last_error TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_cloud_connections_public_id (public_id),
  UNIQUE KEY uq_cloud_connections_user_provider (user_id, provider),
  KEY idx_cloud_connections_status (provider, status),
  CONSTRAINT fk_cloud_connections_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE sync_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  storage_location_id BIGINT UNSIGNED NULL,
  cloud_connection_id BIGINT UNSIGNED NULL,
  document_version_id BIGINT UNSIGNED NOT NULL,
  direction ENUM('push','pull','replicate') NOT NULL,
  status ENUM('queued','running','succeeded','failed','cancelled') NOT NULL DEFAULT 'queued',
  attempts SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  remote_object_id VARCHAR(1000) NULL,
  error_message TEXT NULL,
  queued_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  started_at DATETIME(6) NULL,
  completed_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_sync_jobs_public_id (public_id),
  KEY idx_sync_jobs_worker (status, queued_at),
  KEY idx_sync_jobs_version (document_version_id, status),
  CONSTRAINT chk_sync_jobs_target CHECK ((storage_location_id IS NULL) <> (cloud_connection_id IS NULL)),
  CONSTRAINT fk_sync_jobs_location FOREIGN KEY (storage_location_id) REFERENCES storage_locations(id),
  CONSTRAINT fk_sync_jobs_connection FOREIGN KEY (cloud_connection_id) REFERENCES cloud_connections(id),
  CONSTRAINT fk_sync_jobs_version FOREIGN KEY (document_version_id) REFERENCES document_versions(id)
) ENGINE=InnoDB;

CREATE TABLE cloud_sync_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  sync_job_id BIGINT UNSIGNED NOT NULL,
  event_type VARCHAR(80) NOT NULL,
  status VARCHAR(50) NOT NULL,
  detail JSON NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_cloud_sync_logs_job (sync_job_id, created_at),
  KEY idx_cloud_sync_logs_created (created_at),
  CONSTRAINT fk_cloud_sync_logs_job FOREIGN KEY (sync_job_id) REFERENCES sync_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE outbox_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  aggregate_type VARCHAR(100) NOT NULL,
  aggregate_id BIGINT UNSIGNED NOT NULL,
  event_type VARCHAR(150) NOT NULL,
  payload JSON NOT NULL,
  status ENUM('pending','processing','published','failed') NOT NULL DEFAULT 'pending',
  attempts SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  locked_at DATETIME(6) NULL,
  locked_by VARCHAR(255) NULL,
  published_at DATETIME(6) NULL,
  last_error TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_outbox_events_public_id (public_id),
  KEY idx_outbox_events_worker (status, available_at, id),
  KEY idx_outbox_events_aggregate (aggregate_type, aggregate_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE backup_policies (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  department_id BIGINT UNSIGNED NULL,
  name VARCHAR(255) NOT NULL,
  required_copies TINYINT UNSIGNED NOT NULL DEFAULT 3,
  required_media TINYINT UNSIGNED NOT NULL DEFAULT 2,
  required_offsite TINYINT UNSIGNED NOT NULL DEFAULT 1,
  schedule_cron VARCHAR(120) NOT NULL,
  retention_days INT UNSIGNED NOT NULL,
  immutable_days INT UNSIGNED NOT NULL DEFAULT 0,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_backup_policies_scope (department_id, is_active),
  CONSTRAINT fk_backup_policies_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE backups (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  backup_policy_id BIGINT UNSIGNED NOT NULL,
  backup_type ENUM('full','incremental','differential','metadata_only') NOT NULL,
  status ENUM('queued','running','succeeded','failed','verified','expired') NOT NULL DEFAULT 'queued',
  started_by BIGINT UNSIGNED NULL,
  started_at DATETIME(6) NULL,
  completed_at DATETIME(6) NULL,
  expires_at DATETIME(6) NULL,
  manifest_sha256 BINARY(32) NULL,
  size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  error_message TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_backups_public_id (public_id),
  KEY idx_backups_policy_status (backup_policy_id, status, created_at DESC),
  KEY idx_backups_expiry (status, expires_at),
  CONSTRAINT fk_backups_policy FOREIGN KEY (backup_policy_id) REFERENCES backup_policies(id),
  CONSTRAINT fk_backups_started_by FOREIGN KEY (started_by) REFERENCES users(id)
) ENGINE=InnoDB;

CREATE TABLE backup_copies (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  backup_id BIGINT UNSIGNED NOT NULL,
  storage_location_id BIGINT UNSIGNED NOT NULL,
  object_key VARCHAR(2000) NOT NULL,
  media_type ENUM('disk','nas','object','cloud','tape') NOT NULL,
  is_offsite BOOLEAN NOT NULL,
  is_immutable BOOLEAN NOT NULL DEFAULT FALSE,
  status ENUM('pending','available','failed','expired') NOT NULL DEFAULT 'pending',
  verified_at DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_backup_copies_location (backup_id, storage_location_id),
  KEY idx_backup_copies_compliance (backup_id, status, is_offsite, media_type),
  CONSTRAINT fk_backup_copies_backup FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE CASCADE,
  CONSTRAINT fk_backup_copies_location FOREIGN KEY (storage_location_id) REFERENCES storage_locations(id)
) ENGINE=InnoDB;

CREATE TABLE restore_tests (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  backup_id BIGINT UNSIGNED NOT NULL,
  tested_by BIGINT UNSIGNED NULL,
  status ENUM('running','passed','failed') NOT NULL,
  started_at DATETIME(6) NOT NULL,
  completed_at DATETIME(6) NULL,
  result_detail JSON NULL,
  PRIMARY KEY (id),
  KEY idx_restore_tests_backup (backup_id, started_at DESC),
  CONSTRAINT fk_restore_tests_backup FOREIGN KEY (backup_id) REFERENCES backups(id),
  CONSTRAINT fk_restore_tests_tested_by FOREIGN KEY (tested_by) REFERENCES users(id)
) ENGINE=InnoDB;

-- Deliberately no foreign keys: audit records must survive source-row deletion
-- and can be moved to an append-only compliance database.
CREATE TABLE audit_logs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  actor_user_id BIGINT UNSIGNED NULL,
  actor_type ENUM('user','service','system','anonymous') NOT NULL,
  action VARCHAR(150) NOT NULL,
  resource_type VARCHAR(100) NOT NULL,
  resource_public_id BINARY(16) NULL,
  department_id BIGINT UNSIGNED NULL,
  request_id BINARY(16) NULL,
  source_ip VARBINARY(16) NULL,
  user_agent VARCHAR(1000) NULL,
  outcome ENUM('success','denied','failed') NOT NULL,
  reason_code VARCHAR(120) NULL,
  before_data JSON NULL,
  after_data JSON NULL,
  detail JSON NULL,
  previous_hash BINARY(32) NULL,
  event_hash BINARY(32) NOT NULL,
  PRIMARY KEY (id, occurred_at),
  KEY idx_audit_actor_time (actor_user_id, occurred_at DESC),
  KEY idx_audit_resource_time (resource_type, resource_public_id, occurred_at DESC),
  KEY idx_audit_department_time (department_id, occurred_at DESC),
  KEY idx_audit_action_time (action, occurred_at DESC),
  KEY idx_audit_request (request_id)
) ENGINE=InnoDB
PARTITION BY RANGE COLUMNS(occurred_at) (
  PARTITION p2026 VALUES LESS THAN ('2027-01-01'),
  PARTITION p2027 VALUES LESS THAN ('2028-01-01'),
  PARTITION p2028 VALUES LESS THAN ('2029-01-01'),
  PARTITION pmax VALUES LESS THAN (MAXVALUE)
);

CREATE TABLE retention_policies (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(100) NOT NULL,
  resource_type VARCHAR(100) NOT NULL,
  department_id BIGINT UNSIGNED NULL,
  retention_days INT UNSIGNED NOT NULL,
  delete_action ENUM('soft_delete','anonymize','archive','purge') NOT NULL,
  legal_basis VARCHAR(1000) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_retention_policies_code (code),
  KEY idx_retention_policies_scope (resource_type, department_id, is_active),
  CONSTRAINT fk_retention_policies_department FOREIGN KEY (department_id) REFERENCES departments(id)
) ENGINE=InnoDB;

CREATE TABLE legal_holds (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  public_id BINARY(16) NOT NULL,
  document_id BIGINT UNSIGNED NOT NULL,
  reason VARCHAR(2000) NOT NULL,
  placed_by BIGINT UNSIGNED NOT NULL,
  placed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  released_by BIGINT UNSIGNED NULL,
  released_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_legal_holds_public_id (public_id),
  KEY idx_legal_holds_document (document_id, released_at),
  CONSTRAINT fk_legal_holds_document FOREIGN KEY (document_id) REFERENCES documents(id),
  CONSTRAINT fk_legal_holds_placed_by FOREIGN KEY (placed_by) REFERENCES users(id),
  CONSTRAINT fk_legal_holds_released_by FOREIGN KEY (released_by) REFERENCES users(id)
) ENGINE=InnoDB;

INSERT IGNORE INTO roles(code, name, description, is_system) VALUES
  ('lecturer', 'Giảng viên', 'Quản lý tài liệu và học phần được giao', TRUE),
  ('new_lecturer', 'Giảng viên mới', 'Tiếp nhận tri thức và quyền hạn chế', TRUE),
  ('department_head', 'Trưởng bộ môn', 'Quản lý phạm vi bộ môn', TRUE),
  ('faculty_dean', 'Trưởng khoa', 'Quản lý phạm vi khoa', TRUE),
  ('administrator', 'Quản trị viên', 'Quản trị toàn hệ thống', TRUE);

INSERT IGNORE INTO permissions(code, resource_type, action, description) VALUES
  ('document.read','document','read','Đọc tài liệu'),
  ('document.create','document','create','Tạo tài liệu'),
  ('document.edit','document','edit','Chỉnh sửa tài liệu'),
  ('document.delete','document','delete','Xóa mềm tài liệu'),
  ('document.purge','document','purge','Xóa vĩnh viễn tài liệu'),
  ('document.share','document','share','Chia sẻ tài liệu'),
  ('document.rollback','document','rollback','Khôi phục phiên bản'),
  ('folder.manage','folder','manage','Quản lý thư mục'),
  ('handover.manage','handover','manage','Quản lý chuyển giao tri thức'),
  ('backup.manage','backup','manage','Quản lý sao lưu'),
  ('audit.read','audit','read','Đọc nhật ký kiểm toán'),
  ('system.admin','system','admin','Quản trị hệ thống');
