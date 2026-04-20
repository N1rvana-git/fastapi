--
-- PostgreSQL database dump
--

\restrict IDHAlC8dhvk0JCQLWbPeC6enoszr75Wa04WIewrbA93CwMcs5M2GQAVPmEa5Itx

-- Dumped from database version 15.17 (Debian 15.17-1.pgdg12+1)
-- Dumped by pg_dump version 15.17 (Debian 15.17-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: myuser
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO myuser;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: myuser
--

COMMENT ON SCHEMA public IS '';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: ai_chat_records; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.ai_chat_records (
    id integer NOT NULL,
    user_id integer NOT NULL,
    role character varying NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.ai_chat_records OWNER TO myuser;

--
-- Name: ai_chat_records_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.ai_chat_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.ai_chat_records_id_seq OWNER TO myuser;

--
-- Name: ai_chat_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.ai_chat_records_id_seq OWNED BY public.ai_chat_records.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO myuser;

--
-- Name: item; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.item (
    id integer NOT NULL,
    name character varying,
    price double precision,
    is_offer boolean,
    image_path character varying,
    owner_id integer,
    inventory integer DEFAULT 1 NOT NULL,
    is_sold boolean,
    embedding public.vector(1024),
    image_embedding public.vector(512)
);


ALTER TABLE public.item OWNER TO myuser;

--
-- Name: item_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.item_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.item_id_seq OWNER TO myuser;

--
-- Name: item_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.item_id_seq OWNED BY public.item.id;


--
-- Name: item_tag; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.item_tag (
    item_id integer NOT NULL,
    tag_id integer NOT NULL
);


ALTER TABLE public.item_tag OWNER TO myuser;

--
-- Name: knowledge_base; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.knowledge_base (
    id integer NOT NULL,
    title character varying NOT NULL,
    content text,
    embedding public.vector(1024),
    image_embedding public.vector(512)
);


ALTER TABLE public.knowledge_base OWNER TO myuser;

--
-- Name: knowledge_base_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.knowledge_base_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.knowledge_base_id_seq OWNER TO myuser;

--
-- Name: knowledge_base_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.knowledge_base_id_seq OWNED BY public.knowledge_base.id;


--
-- Name: orders; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.orders (
    id integer NOT NULL,
    buyer_id integer NOT NULL,
    item_id integer NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.orders OWNER TO myuser;

--
-- Name: orders_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.orders_id_seq OWNER TO myuser;

--
-- Name: orders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.orders_id_seq OWNED BY public.orders.id;


--
-- Name: tags; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.tags (
    id integer NOT NULL,
    name character varying
);


ALTER TABLE public.tags OWNER TO myuser;

--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.tags_id_seq OWNER TO myuser;

--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: myuser
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying,
    age integer NOT NULL,
    email character varying,
    phone character varying,
    hashed_password character varying,
    feishu_open_id character varying,
    role character varying DEFAULT 'user'::character varying NOT NULL
);


ALTER TABLE public.users OWNER TO myuser;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: myuser
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.users_id_seq OWNER TO myuser;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: myuser
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: ai_chat_records id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.ai_chat_records ALTER COLUMN id SET DEFAULT nextval('public.ai_chat_records_id_seq'::regclass);


--
-- Name: item id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item ALTER COLUMN id SET DEFAULT nextval('public.item_id_seq'::regclass);


--
-- Name: knowledge_base id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.knowledge_base ALTER COLUMN id SET DEFAULT nextval('public.knowledge_base_id_seq'::regclass);


--
-- Name: orders id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.orders ALTER COLUMN id SET DEFAULT nextval('public.orders_id_seq'::regclass);


--
-- Name: tags id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Data for Name: ai_chat_records; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.ai_chat_records (id, user_id, role, content, created_at) FROM stdin;
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.alembic_version (version_num) FROM stdin;
c924f1debfb5
\.


--
-- Data for Name: item; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.item (id, name, price, is_offer, image_path, owner_id, inventory, is_sold, embedding, image_embedding) FROM stdin;
\.


--
-- Data for Name: item_tag; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.item_tag (item_id, tag_id) FROM stdin;
\.


--
-- Data for Name: knowledge_base; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.knowledge_base (id, title, content, embedding, image_embedding) FROM stdin;
\.


--
-- Data for Name: orders; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.orders (id, buyer_id, item_id, status, created_at) FROM stdin;
\.


--
-- Data for Name: tags; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.tags (id, name) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: myuser
--

COPY public.users (id, username, age, email, phone, hashed_password, feishu_open_id, role) FROM stdin;
\.


--
-- Name: ai_chat_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.ai_chat_records_id_seq', 1, false);


--
-- Name: item_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.item_id_seq', 1, false);


--
-- Name: knowledge_base_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.knowledge_base_id_seq', 1, false);


--
-- Name: orders_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.orders_id_seq', 1, false);


--
-- Name: tags_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.tags_id_seq', 1, false);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: myuser
--

SELECT pg_catalog.setval('public.users_id_seq', 1, false);


--
-- Name: ai_chat_records ai_chat_records_ai_chat_records_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.ai_chat_records
    ADD CONSTRAINT ai_chat_records_ai_chat_records_id_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: item item_item_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_item_id_pkey PRIMARY KEY (id);


--
-- Name: item_tag item_tag_item_tag_item_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item_tag
    ADD CONSTRAINT item_tag_item_tag_item_id_pkey PRIMARY KEY (item_id, tag_id);


--
-- Name: knowledge_base knowledge_base_knowledge_base_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.knowledge_base
    ADD CONSTRAINT knowledge_base_knowledge_base_id_pkey PRIMARY KEY (id);


--
-- Name: orders orders_orders_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_orders_id_pkey PRIMARY KEY (id);


--
-- Name: tags tags_tags_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_tags_id_pkey PRIMARY KEY (id);


--
-- Name: users users_users_id_pkey; Type: CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_users_id_pkey PRIMARY KEY (id);


--
-- Name: ai_chat_records_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX ai_chat_records_id_idx ON public.ai_chat_records USING btree (id);


--
-- Name: item_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX item_id_idx ON public.item USING btree (id);


--
-- Name: item_name_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX item_name_idx ON public.item USING btree (name);


--
-- Name: knowledge_base_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX knowledge_base_id_idx ON public.knowledge_base USING btree (id);


--
-- Name: orders_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX orders_id_idx ON public.orders USING btree (id);


--
-- Name: tags_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX tags_id_idx ON public.tags USING btree (id);


--
-- Name: tags_name_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE UNIQUE INDEX tags_name_idx ON public.tags USING btree (name);


--
-- Name: users_email_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX users_email_idx ON public.users USING btree (email);


--
-- Name: users_feishu_open_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE UNIQUE INDEX users_feishu_open_id_idx ON public.users USING btree (feishu_open_id);


--
-- Name: users_id_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX users_id_idx ON public.users USING btree (id);


--
-- Name: users_phone_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX users_phone_idx ON public.users USING btree (phone);


--
-- Name: users_username_idx; Type: INDEX; Schema: public; Owner: myuser
--

CREATE INDEX users_username_idx ON public.users USING btree (username);


--
-- Name: ai_chat_records ai_chat_records_ai_chat_records_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.ai_chat_records
    ADD CONSTRAINT ai_chat_records_ai_chat_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: item item_item_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_item_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: item_tag item_tag_item_tag_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item_tag
    ADD CONSTRAINT item_tag_item_tag_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id);


--
-- Name: item_tag item_tag_item_tag_tag_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.item_tag
    ADD CONSTRAINT item_tag_item_tag_tag_id_fkey FOREIGN KEY (tag_id) REFERENCES public.tags(id);


--
-- Name: orders orders_orders_buyer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_orders_buyer_id_fkey FOREIGN KEY (buyer_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: orders orders_orders_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: myuser
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_orders_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id) ON DELETE RESTRICT;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: myuser
--

REVOKE USAGE ON SCHEMA public FROM PUBLIC;


--
-- PostgreSQL database dump complete
--

\unrestrict IDHAlC8dhvk0JCQLWbPeC6enoszr75Wa04WIewrbA93CwMcs5M2GQAVPmEa5Itx

